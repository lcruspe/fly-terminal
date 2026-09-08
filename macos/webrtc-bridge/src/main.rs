use std::collections::HashMap;
use std::env;
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::{anyhow, Result};
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::routing::{get, post};
use axum::{Json, Router};
use base64::Engine;
use bytes::Bytes;
use futures_util::{SinkExt, StreamExt};
use hmac::{Hmac, Mac};
use rtcp::payload_feedbacks::full_intra_request::FullIntraRequest;
use rtcp::payload_feedbacks::picture_loss_indication::PictureLossIndication;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha1::Sha1;
use tokio::sync::{mpsc, Notify, RwLock};
use tokio::time::sleep;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::Message;
use uuid::Uuid;
use webrtc::api::interceptor_registry::register_default_interceptors;
use webrtc::api::media_engine::{MediaEngine, MIME_TYPE_H264};
use webrtc::api::APIBuilder;
use webrtc::data_channel::data_channel_message::DataChannelMessage;
use webrtc::data_channel::RTCDataChannel;
use webrtc::ice_transport::ice_server::RTCIceServer;
use webrtc::interceptor::registry::Registry;
use webrtc::peer_connection::configuration::RTCConfiguration;
use webrtc::peer_connection::peer_connection_state::RTCPeerConnectionState;
use webrtc::peer_connection::sdp::session_description::RTCSessionDescription;
use webrtc::peer_connection::RTCPeerConnection;
use webrtc::rtp::{codecs::h264::H264Payloader, packet::Packet, packetizer::Payloader};
use webrtc::rtp_transceiver::rtp_codec::RTCRtpCodecCapability;
use webrtc::track::track_local::track_local_static_rtp::TrackLocalStaticRTP;
use webrtc::track::track_local::{TrackLocal, TrackLocalWriter};

const FRAME_QUEUE: usize = 8;
const DEFAULT_FPS: u32 = 60;
const TURN_TTL_SECONDS: u64 = 600;

// RTP time follows capture time, including static-screen gaps and dropped frames.
// Keep it monotonic if an older encoder uses a different epoch after a restart.
#[derive(Default)]
struct MediaClock {
    previous_us: Option<u64>,
    ticks: u64,
    remainder: u64,
}

impl MediaClock {
    fn timestamp(&mut self, capture_us: u64) -> u32 {
        if let Some(previous) = self.previous_us {
            let delta = capture_us
                .checked_sub(previous)
                .filter(|v| *v > 0)
                .unwrap_or(16_667);
            let scaled = delta.saturating_mul(9).saturating_add(self.remainder);
            self.ticks = self.ticks.wrapping_add(scaled / 100);
            self.remainder = scaled % 100;
        }
        self.previous_us = Some(capture_us);
        self.ticks as u32
    }
}

type HmacSha1 = Hmac<Sha1>;
type ApiError = (StatusCode, String);

#[derive(Clone)]
struct BridgeConfig {
    bind: String,
    source_url: String,
    stun_urls: Vec<String>,
    turn_urls: Vec<String>,
    turn_secret: Option<String>,
    turn_username: Option<String>,
    turn_password: Option<String>,
}

impl BridgeConfig {
    fn from_env() -> Self {
        Self {
            bind: env::var("FLY_WEBRTC_BIND").unwrap_or_else(|_| "127.0.0.1:5907".into()),
            source_url: env::var("FLY_WEBRTC_SOURCE_URL")
                .unwrap_or_else(|_| "ws://127.0.0.1:5905".into()),
            stun_urls: split_env("FLY_WEBRTC_STUN_URLS", "stun:stun.l.google.com:19302"),
            turn_urls: split_env("FLY_TURN_URLS", ""),
            turn_secret: env::var("FLY_TURN_SECRET").ok().filter(|v| !v.is_empty()),
            turn_username: env::var("FLY_TURN_USERNAME").ok().filter(|v| !v.is_empty()),
            turn_password: env::var("FLY_TURN_PASSWORD").ok().filter(|v| !v.is_empty()),
        }
    }
}

fn split_env(name: &str, default: &str) -> Vec<String> {
    env::var(name)
        .unwrap_or_else(|_| default.to_owned())
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .collect()
}
#[derive(Clone)]
struct Frame {
    data: Bytes,
    capture_us: u64,
    queued_at: Instant,
    is_key: bool,
    generation: u64,
}

struct PeerMedia {
    pc: Arc<RTCPeerConnection>,
    frame_tx: mpsc::Sender<Frame>,
    reliable: RwLock<Option<Arc<RTCDataChannel>>>,
    waiting_for_keyframe: AtomicBool,
    generation: Arc<AtomicU64>,
}

struct Hub {
    config: BridgeConfig,
    peers: RwLock<HashMap<String, Arc<PeerMedia>>>,
    control_owner: RwLock<Option<String>>,
    source_tx: RwLock<Option<mpsc::UnboundedSender<String>>>,
    source_notify: Notify,
    source_snapshots: RwLock<HashMap<String, String>>,
    fps: AtomicU32,
}

impl Hub {
    fn new(config: BridgeConfig) -> Self {
        Self {
            config,
            peers: RwLock::new(HashMap::new()),
            control_owner: RwLock::new(None),
            source_tx: RwLock::new(None),
            source_notify: Notify::new(),
            source_snapshots: RwLock::new(HashMap::new()),
            fps: AtomicU32::new(DEFAULT_FPS),
        }
    }
    async fn add_peer(&self, id: String, peer: Arc<PeerMedia>) {
        self.peers.write().await.insert(id.clone(), peer);
        let mut owner = self.control_owner.write().await;
        if owner.is_none() {
            *owner = Some(id);
        }
        drop(owner);
        self.source_notify.notify_waiters();
    }

    async fn remove_peer(&self, id: &str) {
        self.peers.write().await.remove(id);
        let mut owner = self.control_owner.write().await;
        if owner.as_deref() == Some(id) {
            *owner = self.peers.read().await.keys().next().cloned();
        }
        drop(owner);
        self.announce_control_owner().await;
        self.source_notify.notify_waiters();
    }

    async fn is_owner(&self, id: &str) -> bool {
        self.control_owner.read().await.as_deref() == Some(id)
    }

    async fn claim_control(&self, id: &str) {
        if !self.peers.read().await.contains_key(id) {
            return;
        }
        *self.control_owner.write().await = Some(id.to_owned());
        self.send_source(json!({"type":"claim_control"}).to_string())
            .await;
        self.announce_control_owner().await;
    }
    async fn announce_control_owner(&self) {
        let owner = self.control_owner.read().await.clone();
        let peers: Vec<(String, Arc<PeerMedia>)> = self
            .peers
            .read()
            .await
            .iter()
            .map(|(id, peer)| (id.clone(), Arc::clone(peer)))
            .collect();
        for (id, peer) in peers {
            if let Some(channel) = peer.reliable.read().await.clone() {
                let _ = channel
                    .send_text(
                        json!({
                            "type": "control",
                            "owner": owner.as_deref() == Some(id.as_str()),
                            "ownerId": owner,
                        })
                        .to_string(),
                    )
                    .await;
            }
        }
    }

    async fn send_source(&self, text: String) {
        if let Some(tx) = self.source_tx.read().await.as_ref() {
            let _ = tx.send(text);
        }
    }

    async fn request_keyframe(&self, reason: &str) {
        self.send_source(json!({"type":"keyframe","reason":reason}).to_string())
            .await;
    }

    async fn forward_from_peer(&self, id: &str, label: &str, text: &str) {
        let mut value: Value = match serde_json::from_str(text) {
            Ok(value) => value,
            Err(_) => return,
        };
        if value.get("type").and_then(Value::as_str) == Some("client_diagnostic") {
            eprintln!(
                "[WebRTC] client={id} video_stalled decoded={} freezes={} buffer_ms={} rtt_ms={}",
                value["framesDecoded"].as_u64().unwrap_or(0),
                value["freezeCount"].as_u64().unwrap_or(0),
                value["playoutBufferMs"].as_f64().unwrap_or(0.0),
                value["rttMs"].as_f64().unwrap_or(0.0)
            );
            return;
        }
        if value.get("type").and_then(Value::as_str) == Some("claim_control") {
            self.claim_control(id).await;
            return;
        }
        if !self.is_owner(id).await {
            return;
        }
        if let Value::Object(ref mut map) = value {
            map.insert(
                "delivery".to_owned(),
                Value::String(
                    if label == "input-motion" {
                        "motion"
                    } else {
                        "reliable"
                    }
                    .to_owned(),
                ),
            );
        }
        self.send_source(value.to_string()).await;
    }

    async fn broadcast_source_text(&self, text: &str) {
        if let Ok(value) = serde_json::from_str::<Value>(text) {
            if let Some(kind) = value.get("type").and_then(Value::as_str) {
                if matches!(kind, "init" | "display" | "status" | "codec") {
                    self.source_snapshots
                        .write()
                        .await
                        .insert(kind.to_owned(), text.to_owned());
                }
            }
        }
        let channels: Vec<Arc<RTCDataChannel>> = self
            .peers
            .read()
            .await
            .values()
            .filter_map(|peer| {
                peer.reliable
                    .try_read()
                    .ok()
                    .and_then(|guard| guard.clone())
            })
            .collect();
        for channel in channels {
            let _ = channel.send_text(text.to_owned()).await;
        }
    }

    async fn send_snapshot(&self, channel: &Arc<RTCDataChannel>) {
        let snapshots: Vec<String> = self
            .source_snapshots
            .read()
            .await
            .values()
            .cloned()
            .collect();
        for snapshot in snapshots {
            let _ = channel.send_text(snapshot).await;
        }
    }

    async fn broadcast_frame(&self, payload: &[u8], is_key: bool, capture_us: u64) {
        let frame = Frame {
            data: Bytes::copy_from_slice(payload),
            capture_us,
            queued_at: Instant::now(),
            is_key,
            generation: 0,
        };
        let peers: Vec<Arc<PeerMedia>> = self.peers.read().await.values().cloned().collect();
        let mut need_keyframe = false;
        for peer in peers {
            if peer.waiting_for_keyframe.load(Ordering::Relaxed) && !is_key {
                continue;
            }
            if is_key {
                peer.waiting_for_keyframe.store(false, Ordering::Relaxed);
            }
            let mut outgoing = frame.clone();
            outgoing.generation = peer.generation.load(Ordering::Relaxed);
            if peer.frame_tx.try_send(outgoing).is_err() {
                peer.generation.fetch_add(1, Ordering::Relaxed);
                peer.waiting_for_keyframe.store(true, Ordering::Relaxed);
                need_keyframe = true;
            }
        }
        if need_keyframe {
            self.request_keyframe("webrtc_peer_queue_overload").await;
        }
    }

    async fn active_peer_count(&self) -> usize {
        self.peers.read().await.len()
    }
}

#[derive(Serialize)]
struct IceServerJson {
    urls: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    username: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    credential: Option<String>,
}

#[derive(Serialize)]
struct ClientConfigResponse {
    ice_servers: Vec<IceServerJson>,
    turn_configured: bool,
    transport: &'static str,
}
fn turn_credentials(config: &BridgeConfig, session: &str) -> Option<(String, String)> {
    if let (Some(username), Some(password)) = (&config.turn_username, &config.turn_password) {
        return Some((username.clone(), password.clone()));
    }
    let secret = config.turn_secret.as_ref()?;
    let expiry = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_secs() + TURN_TTL_SECONDS;
    let username = format!("{expiry}:{session}");
    let mut mac = HmacSha1::new_from_slice(secret.as_bytes()).ok()?;
    mac.update(username.as_bytes());
    let credential = base64::engine::general_purpose::STANDARD.encode(mac.finalize().into_bytes());
    Some((username, credential))
}

fn ice_servers_for(config: &BridgeConfig, session: &str) -> Vec<RTCIceServer> {
    let mut result = Vec::new();
    if !config.stun_urls.is_empty() {
        result.push(RTCIceServer {
            urls: config.stun_urls.clone(),
            ..Default::default()
        });
    }
    if !config.turn_urls.is_empty() {
        if let Some((username, credential)) = turn_credentials(config, session) {
            result.push(RTCIceServer {
                urls: config.turn_urls.clone(),
                username,
                credential,
            });
        }
    }
    result
}
async fn client_config(State(hub): State<Arc<Hub>>) -> Json<ClientConfigResponse> {
    let session = Uuid::new_v4().to_string();
    let mut servers = Vec::new();
    if !hub.config.stun_urls.is_empty() {
        servers.push(IceServerJson {
            urls: hub.config.stun_urls.clone(),
            username: None,
            credential: None,
        });
    }
    let mut turn_configured = false;
    if !hub.config.turn_urls.is_empty() {
        if let Some((username, credential)) = turn_credentials(&hub.config, &session) {
            servers.push(IceServerJson {
                urls: hub.config.turn_urls.clone(),
                username: Some(username),
                credential: Some(credential),
            });
            turn_configured = true;
        }
    }
    Json(ClientConfigResponse {
        ice_servers: servers,
        turn_configured,
        transport: "webrtc",
    })
}

#[derive(Deserialize)]
struct OfferRequest {
    sdp: RTCSessionDescription,
}

#[derive(Serialize)]
struct OfferResponse {
    session_id: String,
    sdp: RTCSessionDescription,
}
async fn build_peer(hub: Arc<Hub>, session_id: String) -> Result<Arc<PeerMedia>> {
    let mut media_engine = MediaEngine::default();
    media_engine.register_default_codecs()?;
    let registry = register_default_interceptors(Registry::new(), &mut media_engine)?;
    let api = APIBuilder::new()
        .with_media_engine(media_engine)
        .with_interceptor_registry(registry)
        .build();
    let pc = Arc::new(
        api.new_peer_connection(RTCConfiguration {
            ice_servers: ice_servers_for(&hub.config, &session_id),
            ..Default::default()
        })
        .await?,
    );

    let track = Arc::new(TrackLocalStaticRTP::new(
        RTCRtpCodecCapability {
            mime_type: MIME_TYPE_H264.to_owned(),
            clock_rate: 90_000,
            sdp_fmtp_line: "level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42002a"
                .to_owned(),
            ..Default::default()
        },
        "video".to_owned(),
        "fly-terminal".to_owned(),
    ));
    let sender = pc
        .add_track(Arc::clone(&track) as Arc<dyn TrackLocal + Send + Sync>)
        .await?;

    let (frame_tx, mut frame_rx) = mpsc::channel::<Frame>(FRAME_QUEUE);
    let track_writer = Arc::clone(&track);
    let generation = Arc::new(AtomicU64::new(0));
    let writer_generation = Arc::clone(&generation);
    let writer_hub = Arc::clone(&hub);
    tokio::spawn(async move {
        let mut payloader = H264Payloader::default();
        let mut sequence: u16 = 0;
        let mut waiting = true;
        let mut clock = MediaClock::default();
        while let Some(frame) = frame_rx.recv().await {
            if frame.generation != writer_generation.load(Ordering::Relaxed)
                || frame.queued_at.elapsed() > Duration::from_millis(100)
            {
                waiting = true;
                writer_hub.request_keyframe("stale_webrtc_frame").await;
                continue;
            }
            if waiting && !frame.is_key {
                continue;
            }
            waiting = false;
            let timestamp = clock.timestamp(frame.capture_us);
            let send = async {
                let payloads = payloader.payload(1188, &frame.data)?;
                let count = payloads.len();
                for (index, payload) in payloads.into_iter().enumerate() {
                    let mut packet = Packet {
                        payload,
                        ..Default::default()
                    };
                    packet.header.version = 2;
                    packet.header.sequence_number = sequence;
                    sequence = sequence.wrapping_add(1);
                    packet.header.timestamp = timestamp;
                    packet.header.marker = index + 1 == count;
                    track_writer.write_rtp(&packet).await?;
                }
                Ok::<(), anyhow::Error>(())
            };
            let result = tokio::time::timeout(Duration::from_millis(200), send).await;
            if !matches!(result, Ok(Ok(()))) {
                let error = format!("{result:?}");
                eprintln!("[WebRTC] RTP write failed: {error}");
                waiting = true;
                writer_hub.request_keyframe("rtp_write_failed").await;
            }
        }
    });
    let peer = Arc::new(PeerMedia {
        pc: Arc::clone(&pc),
        frame_tx,
        reliable: RwLock::new(None),
        waiting_for_keyframe: AtomicBool::new(true),
        generation,
    });

    let rtcp_hub = Arc::clone(&hub);
    tokio::spawn(async move {
        while let Ok((packets, _)) = sender.read_rtcp().await {
            let wants_keyframe = packets.iter().any(|packet| {
                packet.as_any().is::<PictureLossIndication>()
                    || packet.as_any().is::<FullIntraRequest>()
            });
            if wants_keyframe {
                rtcp_hub.request_keyframe("rtcp_pli_fir").await;
            }
        }
    });

    let dc_hub = Arc::clone(&hub);
    let dc_peer = Arc::clone(&peer);
    let dc_session = session_id.clone();
    pc.on_data_channel(Box::new(move |channel: Arc<RTCDataChannel>| {
        let hub = Arc::clone(&dc_hub);
        let peer = Arc::clone(&dc_peer);
        let session = dc_session.clone();
        let label = channel.label().to_owned();
        Box::pin(async move {
            if label == "input-reliable" {
                *peer.reliable.write().await = Some(Arc::clone(&channel));
            }
            let open_hub = Arc::clone(&hub);
            let open_channel = Arc::clone(&channel);
            channel.on_open(Box::new(move || {
                let hub = Arc::clone(&open_hub);
                let channel = Arc::clone(&open_channel);
                Box::pin(async move {
                    hub.send_snapshot(&channel).await;
                    hub.announce_control_owner().await;
                })
            }));

            let message_hub = Arc::clone(&hub);
            let message_session = session.clone();
            let message_label = label.clone();
            channel.on_message(Box::new(move |message: DataChannelMessage| {
                let hub = Arc::clone(&message_hub);
                let session = message_session.clone();
                let label = message_label.clone();
                Box::pin(async move {
                    if let Ok(text) = String::from_utf8(message.data.to_vec()) {
                        hub.forward_from_peer(&session, &label, &text).await;
                    }
                })
            }));
        })
    }));

    let state_hub = Arc::clone(&hub);
    let state_session = session_id.clone();
    let state_peer = Arc::clone(&peer);
    pc.on_peer_connection_state_change(Box::new(move |state: RTCPeerConnectionState| {
        let hub = Arc::clone(&state_hub);
        let session = state_session.clone();
        let pc = Arc::clone(&state_peer.pc);
        Box::pin(async move {
            if state == RTCPeerConnectionState::Closed {
                hub.remove_peer(&session).await;
            } else if state == RTCPeerConnectionState::Failed {
                sleep(Duration::from_secs(15)).await;
                if pc.connection_state() == RTCPeerConnectionState::Failed {
                    hub.remove_peer(&session).await;
                    let _ = pc.close().await;
                }
            }
        })
    }));

    Ok(peer)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rtp_clock_preserves_idle_and_dropped_frame_gaps() {
        let mut clock = MediaClock::default();
        assert_eq!(clock.timestamp(1_000_000), 0);
        assert_eq!(clock.timestamp(1_016_667), 1500);
        assert_eq!(clock.timestamp(3_000_000), 180_000);
        assert_eq!(clock.timestamp(3_100_000), 189_000);
        assert!(clock.timestamp(100) > 189_000);
    }

    #[test]
    fn extended_packet_retains_capture_time_and_h264() {
        let mut packet = vec![0u8; 34];
        packet[0] = 0x81;
        packet[1] = 1;
        packet[10..18].copy_from_slice(&1234567u64.to_be_bytes());
        packet.extend_from_slice(&[0, 0, 0, 1, 0x65]);
        let (payload, key, pts) = h264_from_stream_packet(&packet).unwrap();
        assert!(key);
        assert_eq!(pts, 1234567);
        assert_eq!(payload, &[0, 0, 0, 1, 0x65]);
        assert!(h264_from_stream_packet(&packet[..8]).is_none());
    }
}
fn internal_error(error: impl std::fmt::Display) -> ApiError {
    (StatusCode::INTERNAL_SERVER_ERROR, error.to_string())
}

async fn negotiate(
    peer: &Arc<PeerMedia>,
    offer: RTCSessionDescription,
) -> Result<RTCSessionDescription> {
    peer.pc.set_remote_description(offer).await?;
    let answer = peer.pc.create_answer(None).await?;
    let mut gather_complete = peer.pc.gathering_complete_promise().await;
    peer.pc.set_local_description(answer).await?;
    let _ = gather_complete.recv().await;
    peer.pc
        .local_description()
        .await
        .ok_or_else(|| anyhow!("local description is missing"))
}

async fn create_offer_answer(
    State(hub): State<Arc<Hub>>,
    Json(request): Json<OfferRequest>,
) -> Result<Json<OfferResponse>, ApiError> {
    let session_id = Uuid::new_v4().to_string();
    let peer = build_peer(Arc::clone(&hub), session_id.clone())
        .await
        .map_err(internal_error)?;
    hub.add_peer(session_id.clone(), Arc::clone(&peer)).await;
    let answer = match negotiate(&peer, request.sdp).await {
        Ok(answer) => answer,
        Err(error) => {
            hub.remove_peer(&session_id).await;
            let _ = peer.pc.close().await;
            return Err(internal_error(error));
        }
    };
    hub.request_keyframe("new_webrtc_peer").await;
    Ok(Json(OfferResponse {
        session_id,
        sdp: answer,
    }))
}
async fn renegotiate(
    State(hub): State<Arc<Hub>>,
    Path(session_id): Path<String>,
    Json(request): Json<OfferRequest>,
) -> Result<Json<OfferResponse>, ApiError> {
    let peer = hub
        .peers
        .read()
        .await
        .get(&session_id)
        .cloned()
        .ok_or((StatusCode::NOT_FOUND, "unknown WebRTC session".to_owned()))?;
    let answer = negotiate(&peer, request.sdp)
        .await
        .map_err(internal_error)?;
    hub.request_keyframe("ice_restart").await;
    Ok(Json(OfferResponse {
        session_id,
        sdp: answer,
    }))
}

async fn close_session(State(hub): State<Arc<Hub>>, Path(session_id): Path<String>) -> StatusCode {
    let peer = hub.peers.read().await.get(&session_id).cloned();
    hub.remove_peer(&session_id).await;
    if let Some(peer) = peer {
        let _ = peer.pc.close().await;
    }
    StatusCode::NO_CONTENT
}

async fn health(State(hub): State<Arc<Hub>>) -> Json<Value> {
    Json(json!({
        "status": "ok",
        "peers": hub.active_peer_count().await,
        "source": hub.config.source_url,
        "turnConfigured": !hub.config.turn_urls.is_empty()
            && (hub.config.turn_secret.is_some()
                || (hub.config.turn_username.is_some() && hub.config.turn_password.is_some())),
    }))
}
fn h264_from_stream_packet(data: &[u8]) -> Option<(&[u8], bool, u64)> {
    if data.is_empty() {
        return None;
    }
    let flags = data[0];
    let is_key = flags & 0x01 != 0;
    let offset = if flags & 0x80 != 0 && data.len() >= 34 && data[1] == 1 {
        34
    } else if data.len() >= 9 {
        9
    } else {
        return None;
    };
    let capture_us = if offset == 34 {
        u64::from_be_bytes(data[10..18].try_into().ok()?)
    } else {
        u64::from_be_bytes(data[1..9].try_into().ok()?).saturating_mul(1000)
    };
    (data.len() > offset).then_some((&data[offset..], is_key, capture_us))
}

async fn source_loop(hub: Arc<Hub>) {
    loop {
        while hub.active_peer_count().await == 0 {
            hub.source_notify.notified().await;
        }

        let socket = match connect_async(&hub.config.source_url).await {
            Ok((socket, _)) => socket,
            Err(error) => {
                eprintln!("[WebRTC] source connect failed: {error}");
                sleep(Duration::from_secs(1)).await;
                continue;
            }
        };
        eprintln!("[WebRTC] connected to source {}", hub.config.source_url);
        let (mut sink, mut stream) = socket.split();
        let (source_tx, mut source_rx) = mpsc::unbounded_channel::<String>();
        *hub.source_tx.write().await = Some(source_tx.clone());
        let _ = source_tx.send(json!({"type":"bridge_hello"}).to_string());
        let _ = source_tx.send(json!({"type":"claim_control"}).to_string());
        let writer = tokio::spawn(async move {
            let mut keepalive = tokio::time::interval(Duration::from_secs(30));
            loop {
                tokio::select! {
                    command = source_rx.recv() => {
                        let Some(command) = command else { break; };
                        if sink.send(Message::Text(command.into())).await.is_err() {
                            break;
                        }
                    }
                    _ = keepalive.tick() => {
                        if sink.send(Message::Text(json!({"type":"bridge_keepalive"}).to_string().into())).await.is_err() {
                            break;
                        }
                    }
                }
            }
        });

        loop {
            if hub.active_peer_count().await == 0 {
                break;
            }
            tokio::select! {
                incoming = stream.next() => {
                    match incoming {
                        Some(Ok(Message::Text(text))) => {
                            if let Ok(value) = serde_json::from_str::<Value>(&text) {
                                if value.get("type").and_then(Value::as_str) == Some("init") {
                                    if let Some(fps) = value.get("fps").and_then(Value::as_u64) {
                                        hub.fps.store((fps as u32).max(1), Ordering::Relaxed);
                                    }
                                }
                            }
                            hub.broadcast_source_text(&text).await;
                        }
                        Some(Ok(Message::Binary(data))) => {
                            if let Some((h264, is_key, capture_us)) = h264_from_stream_packet(&data) {
                                hub.broadcast_frame(h264, is_key, capture_us).await;
                            }
                        }
                        Some(Ok(Message::Close(_))) | None => break,
                        Some(Err(error)) => {
                            eprintln!("[WebRTC] source read failed: {error}");
                            break;
                        }
                        _ => {}
                    }
                }
                _ = sleep(Duration::from_millis(500)) => {}
            }
        }

        *hub.source_tx.write().await = None;
        writer.abort();
        for peer in hub.peers.read().await.values() {
            peer.waiting_for_keyframe.store(true, Ordering::Relaxed);
        }
        if hub.active_peer_count().await > 0 {
            sleep(Duration::from_millis(300)).await;
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let config = BridgeConfig::from_env();
    let bind = config.bind.clone();
    let hub = Arc::new(Hub::new(config));
    tokio::spawn(source_loop(Arc::clone(&hub)));
    let app = Router::new()
        .route("/health", get(health))
        .route("/config", get(client_config))
        .route("/offer", post(create_offer_answer))
        .route("/session/:id/renegotiate", post(renegotiate))
        .route("/session/:id/close", post(close_session))
        .with_state(hub);

    let listener = tokio::net::TcpListener::bind(&bind).await?;
    eprintln!("[WebRTC] bridge listening on {bind}");
    axum::serve(listener, app).await?;
    Ok(())
}
