import Foundation
import ScreenCaptureKit
import VideoToolbox
import CoreVideo
import CoreMedia
import CoreGraphics
import IOKit.pwr_mgt
import AppKit
import Darwin

final class EncodedFrameContext {
    let frameID: UInt64
    let capturePTSUs: UInt64
    let encodeStartNs: UInt64

    init(frameID: UInt64, capturePTSUs: UInt64, encodeStartNs: UInt64) {
        self.frameID = frameID
        self.capturePTSUs = capturePTSUs
        self.encodeStartNs = encodeStartNs
    }
}

final class ScreenEncoder: NSObject, SCStreamOutput, SCStreamDelegate {
    private var scStream: SCStream?
    private var compressionSession: VTCompressionSession?
    private var frameIndex: UInt64 = 0
    private var forceNextKeyframe = true
    private let targetWidth: Int32
    private let targetHeight: Int32
    private let fps: Int32
    private var bitrate: Int32
    private let displayName: String
    private let queue = DispatchQueue(label: "ai.kruspe.fly-terminal.encoder", qos: .userInteractive)
    private let outputQueue = DispatchQueue(label: "ai.kruspe.fly-terminal.encoder.output", qos: .userInteractive)
    private let stateLock = NSLock()
    private let outHandle = FileHandle.standardOutput
    private var socketFD: Int32 = -1
    private var pendingEncodes = 0
    private var pendingOutputBytes = 0
    private let maxPendingEncodes = 2
    private let maxPendingOutputBytes = 8 * 1024 * 1024
    private var powerAssertionID: IOPMAssertionID = 0
    private var isCapturing = false
    
    init(width: Int32 = 1920, height: Int32 = 1080, fps: Int32 = 60, bitrate: Int32 = 4_500_000, displayName: String = "") {
        self.targetWidth = width
        self.targetHeight = height
        self.fps = fps
        self.bitrate = bitrate
        self.displayName = displayName
        super.init()
        connectUnixSocket()
    }
    
    private func connectUnixSocket() {
        let sockPath = ProcessInfo.processInfo.environment["FLY_STREAMER_SOCKET_PATH"] ?? "/tmp/fly-mac-stream.sock"
        guard socketFD < 0 else { return }
        guard FileManager.default.fileExists(atPath: sockPath) else { return }
        
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { return }
        
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let len = sockPath.utf8.count
        _ = withUnsafeMutablePointer(to: &addr.sun_path.0) { ptr in
            sockPath.withCString { cstr in
                strncpy(ptr, cstr, 103)
            }
        }
        let addrLen = socklen_t(MemoryLayout<sa_family_t>.size + len)
        let res = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockPtr in
                connect(fd, sockPtr, addrLen)
            }
        }
        if res == 0 {
            self.socketFD = fd
            fputs("[Encoder] Connected to Unix socket \(sockPath)\n", stderr)
        } else {
            close(fd)
        }
    }
    
    func start() {
        _ = CGRequestScreenCaptureAccess()
        acquirePowerAssertion()
        startControlLoop()
        Task {
            await startCaptureLoop()
        }
    }

    private func startControlLoop() {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            while let line = readLine() {
                guard
                    let data = line.data(using: .utf8),
                    let command = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                    let type = command["type"] as? String
                else { continue }
                self?.queue.async {
                    guard let self else { return }
                    if type == "keyframe" {
                        self.forceNextKeyframe = true
                    } else if type == "bitrate", let value = command["value"] as? NSNumber {
                        self.applyBitrate(Int32(clamping: value.intValue))
                    }
                }
            }
        }
    }
    
    private func acquirePowerAssertion() {
        if powerAssertionID == 0 {
            IOPMAssertionCreateWithName(
                kIOPMAssertionTypePreventUserIdleDisplaySleep as CFString,
                IOPMAssertionLevel(kIOPMAssertionLevelOn),
                "Fly Terminal Remote Desktop Streaming" as CFString,
                &powerAssertionID
            )
        }
    }
    
    private func releasePowerAssertion() {
        if powerAssertionID != 0 {
            IOPMAssertionRelease(powerAssertionID)
            powerAssertionID = 0
        }
    }
    
    private func startCaptureLoop() async {
        while true {
            do {
                let proc = Process()
                proc.executableURL = URL(fileURLWithPath: "/usr/bin/caffeinate")
                proc.arguments = ["-u", "-t", "2"]
                try? proc.run()
                
                try await Task.sleep(nanoseconds: 200_000_000)
                
                let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
                let requestedDisplayID: CGDirectDisplayID
                if displayName.isEmpty {
                    requestedDisplayID = CGMainDisplayID()
                } else {
                    let screenNumber = NSScreen.screens.first(where: { $0.localizedName == displayName })?
                        .deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber
                    requestedDisplayID = screenNumber.map { CGDirectDisplayID($0.uint32Value) } ?? CGMainDisplayID()
                }
                let display = content.displays.first(where: { $0.displayID == requestedDisplayID }) ?? content.displays.first
                guard let display = display else {
                    fputs("[Encoder] No active displays found. Retrying in 2s...\n", stderr)
                    try await Task.sleep(nanoseconds: 2_000_000_000)
                    continue
                }
                let displayBounds = CGDisplayBounds(display.displayID)
                fputs("[Encoder] Display geometry id=\(display.displayID) name=\(displayName.isEmpty ? "default" : displayName) x=\(Int(displayBounds.origin.x)) y=\(Int(displayBounds.origin.y)) width=\(Int(displayBounds.width)) height=\(Int(displayBounds.height))\n", stderr)
                
                fputs("[Encoder] Found display \(display.displayID): \(display.width)x\(display.height)\n", stderr)
                setupVideoToolbox()
                
                let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
                let config = SCStreamConfiguration()
                config.width = Int(targetWidth)
                config.height = Int(targetHeight)
                config.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(fps))
                config.showsCursor = false
                config.pixelFormat = kCVPixelFormatType_32BGRA
                let configuredDepth = Int(ProcessInfo.processInfo.environment["FLY_STREAMER_CAPTURE_QUEUE_DEPTH"] ?? "") ?? 2
                config.queueDepth = max(1, min(4, configuredDepth))
                
                let stream = SCStream(filter: filter, configuration: config, delegate: self)
                try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
                try await stream.startCapture()
                self.scStream = stream
                self.isCapturing = true
                fputs("[Encoder] Capture started at \(targetWidth)x\(targetHeight) @ \(fps) FPS\n", stderr)
                return
            } catch {
                fputs("[Encoder] Capture setup error: \(error). Retrying in 2s...\n", stderr)
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }
    
    private func setEncoderProperty(_ session: VTCompressionSession, key: CFString, value: CFTypeRef, name: String) -> Bool {
        let status = VTSessionSetProperty(session, key: key, value: value)
        if status != noErr {
            fputs("[Encoder] VideoToolbox property \(name) rejected: \(status)\n", stderr)
            return false
        }
        return true
    }

    private func createCompressionSession(specification: CFDictionary?) -> (OSStatus, VTCompressionSession?) {
        let callback: VTCompressionOutputCallback = { refCon, sourceFrameRefCon, status, _, sampleBuffer in
            guard let refCon else { return }
            let encoder = Unmanaged<ScreenEncoder>.fromOpaque(refCon).takeUnretainedValue()
            let context = sourceFrameRefCon.map {
                Unmanaged<EncodedFrameContext>.fromOpaque($0).takeRetainedValue()
            }
            encoder.finishEncodedFrame(status: status, sampleBuffer: sampleBuffer, context: context)
        }
        var session: VTCompressionSession?
        let status = VTCompressionSessionCreate(
            allocator: kCFAllocatorDefault,
            width: targetWidth,
            height: targetHeight,
            codecType: kCMVideoCodecType_H264,
            encoderSpecification: specification,
            imageBufferAttributes: nil,
            compressedDataAllocator: nil,
            outputCallback: callback,
            refcon: Unmanaged.passUnretained(self).toOpaque(),
            compressionSessionOut: &session
        )
        return (status, session)
    }

    private func setupVideoToolbox() {
        if let existing = compressionSession {
            VTCompressionSessionInvalidate(existing)
            compressionSession = nil
        }

        let lowLatencySpec: [CFString: Any] = [
            kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder: true,
            kVTVideoEncoderSpecification_EnableLowLatencyRateControl: true,
        ]
        var (status, session) = createCompressionSession(specification: lowLatencySpec as CFDictionary)
        let lowLatencyEnabled = status == noErr && session != nil
        if !lowLatencyEnabled {
            fputs("[Encoder] Low-latency hardware encoder unavailable (\(status)); retrying hardware H.264\n", stderr)
            let hardwareSpec: [CFString: Any] = [
                kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder: true,
            ]
            (status, session) = createCompressionSession(specification: hardwareSpec as CFDictionary)
        }

        guard status == noErr, let session else {
            fputs("[Encoder] VTCompressionSessionCreate failed: \(status)\n", stderr)
            return
        }

        _ = setEncoderProperty(session, key: kVTCompressionPropertyKey_RealTime, value: kCFBooleanTrue, name: "RealTime")
        _ = setEncoderProperty(
            session,
            key: kVTCompressionPropertyKey_ProfileLevel,
            value: kVTProfileLevel_H264_Baseline_AutoLevel,
            name: "ProfileLevel"
        )
        _ = setEncoderProperty(session, key: kVTCompressionPropertyKey_AverageBitRate, value: bitrate as CFNumber, name: "AverageBitRate")
        _ = setEncoderProperty(session, key: kVTCompressionPropertyKey_ExpectedFrameRate, value: fps as CFNumber, name: "ExpectedFrameRate")
        _ = setEncoderProperty(session, key: kVTCompressionPropertyKey_MaxKeyFrameInterval, value: (fps * 2) as CFNumber, name: "MaxKeyFrameInterval")
        _ = setEncoderProperty(session, key: kVTCompressionPropertyKey_AllowFrameReordering, value: kCFBooleanFalse, name: "AllowFrameReordering")

        let prepareStatus = VTCompressionSessionPrepareToEncodeFrames(session)
        if prepareStatus != noErr {
            fputs("[Encoder] VTCompressionSessionPrepareToEncodeFrames failed: \(prepareStatus)\n", stderr)
        }
        var hardwareValue: CFTypeRef?
        let hardwareStatus = withUnsafeMutablePointer(to: &hardwareValue) { pointer in
            VTSessionCopyProperty(
                session,
                key: kVTCompressionPropertyKey_UsingHardwareAcceleratedVideoEncoder,
                allocator: kCFAllocatorDefault,
                valueOut: UnsafeMutableRawPointer(pointer)
            )
        }
        let hardware = hardwareStatus == noErr && (hardwareValue as? Bool == true)
        fputs("[Encoder] VideoToolbox ready: hardware=\(hardware) hardwareQueryStatus=\(hardwareStatus) hardwareValue=\(String(describing: hardwareValue)) requiredHardware=true lowLatency=\(lowLatencyEnabled) bitrate=\(bitrate)\n", stderr)
        self.compressionSession = session
    }

    private func monotonicHostTimeNs() -> UInt64 {
        let hostTime = CMClockGetTime(CMClockGetHostTimeClock())
        let nanoseconds = CMTimeConvertScale(hostTime, timescale: 1_000_000_000, method: .default)
        return nanoseconds.isValid && nanoseconds.value > 0 ? UInt64(nanoseconds.value) : DispatchTime.now().uptimeNanoseconds
    }

    private func applyBitrate(_ requested: Int32) {
        let clamped = max(300_000, min(20_000_000, requested))
        bitrate = clamped
        guard let session = compressionSession else { return }
        if setEncoderProperty(session, key: kVTCompressionPropertyKey_AverageBitRate, value: clamped as CFNumber, name: "AverageBitRate(runtime)") {
            fputs("[Encoder] Bitrate changed to \(clamped) bps\n", stderr)
        }
    }
    
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, let pixelBuffer = sampleBuffer.imageBuffer, let session = compressionSession else { return }
        guard
            let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
            let statusRaw = attachments.first?[.status] as? Int,
            let frameStatus = SCFrameStatus(rawValue: statusRaw),
            frameStatus == .complete
        else { return }

        stateLock.lock()
        if pendingEncodes >= maxPendingEncodes {
            stateLock.unlock()
            return
        }
        pendingEncodes += 1
        stateLock.unlock()

        frameIndex += 1
        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        let capturePTS = CMTimeConvertScale(pts, timescale: 1_000_000, method: .default)
        let capturePTSUs = capturePTS.isValid && capturePTS.value > 0 ? UInt64(capturePTS.value) : 0
        let durationValue = CMSampleBufferGetDuration(sampleBuffer)
        let duration = durationValue.isValid && durationValue.value > 0
            ? durationValue
            : CMTime(value: 1, timescale: CMTimeScale(fps))
        let context = EncodedFrameContext(
            frameID: frameIndex,
            capturePTSUs: capturePTSUs,
            encodeStartNs: monotonicHostTimeNs()
        )
        var props: [CFString: Any]? = nil
        if forceNextKeyframe || (frameIndex % UInt64(fps * 2) == 0) {
            props = [kVTEncodeFrameOptionKey_ForceKeyFrame: true]
            forceNextKeyframe = false
        }
        let retainedContext = Unmanaged.passRetained(context).toOpaque()
        let encodeStatus = VTCompressionSessionEncodeFrame(
            session,
            imageBuffer: pixelBuffer,
            presentationTimeStamp: pts,
            duration: duration,
            frameProperties: props as CFDictionary?,
            sourceFrameRefcon: retainedContext,
            infoFlagsOut: nil
        )
        if encodeStatus != noErr {
            Unmanaged<EncodedFrameContext>.fromOpaque(retainedContext).release()
            stateLock.lock()
            pendingEncodes = max(0, pendingEncodes - 1)
            stateLock.unlock()
            fputs("[Encoder] VTCompressionSessionEncodeFrame failed: \(encodeStatus)\n", stderr)
        }
    }

    private func finishEncodedFrame(status: OSStatus, sampleBuffer: CMSampleBuffer?, context: EncodedFrameContext?) {
        stateLock.lock()
        pendingEncodes = max(0, pendingEncodes - 1)
        stateLock.unlock()
        guard status == noErr, let sampleBuffer, let context else {
            if status != noErr {
                fputs("[Encoder] VideoToolbox callback failed: \(status)\n", stderr)
            }
            return
        }
        outputFrame(sampleBuffer: sampleBuffer, context: context)
    }
    
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fputs("[Encoder] Stream stopped: \(error). Reconnecting...\n", stderr)
        isCapturing = false
        Task {
            await startCaptureLoop()
        }
    }
    
    private func appendBigEndian(_ value: UInt64, to data: inout Data) {
        var bigEndian = value.bigEndian
        withUnsafeBytes(of: &bigEndian) { data.append(contentsOf: $0) }
    }

    private func writePacket(_ packet: Data) {
        if socketFD < 0 {
            connectUnixSocket()
        }
        var writtenSuccessfully = false
        if socketFD >= 0 {
            writtenSuccessfully = packet.withUnsafeBytes { raw -> Bool in
                guard let base = raw.baseAddress else { return false }
                var offset = 0
                while offset < raw.count {
                    let written = Darwin.write(socketFD, base.advanced(by: offset), raw.count - offset)
                    if written > 0 {
                        offset += written
                        continue
                    }
                    if written < 0 && errno == EINTR {
                        continue
                    }
                    return false
                }
                return true
            }
            if !writtenSuccessfully {
                close(socketFD)
                socketFD = -1
            }
        }
        if !writtenSuccessfully {
            do {
                try outHandle.write(contentsOf: packet)
            } catch {
                fputs("[Encoder] stdout frame write failed: \(error)\n", stderr)
            }
        }
        stateLock.lock()
        pendingOutputBytes = max(0, pendingOutputBytes - packet.count)
        stateLock.unlock()
    }

    private func outputFrame(sampleBuffer: CMSampleBuffer, context: EncodedFrameContext) {
        guard let (h264Data, isKeyFrame) = extractAnnexB(from: sampleBuffer) else { return }

        let headerLength = 34
        let payloadLen = UInt32(headerLength + h264Data.count)
        var lenBig = payloadLen.bigEndian
        var flags: UInt8 = (isKeyFrame ? 0x01 : 0x00) | 0x80
        var version: UInt8 = 1
        let encodeDoneNs = monotonicHostTimeNs()

        var packet = Data(capacity: 4 + Int(payloadLen))
        withUnsafeBytes(of: &lenBig) { packet.append(contentsOf: $0) }
        packet.append(&flags, count: 1)
        packet.append(&version, count: 1)
        appendBigEndian(context.frameID, to: &packet)
        appendBigEndian(context.capturePTSUs, to: &packet)
        appendBigEndian(context.encodeStartNs, to: &packet)
        appendBigEndian(encodeDoneNs, to: &packet)
        packet.append(h264Data)

        stateLock.lock()
        let wouldOverflow = pendingOutputBytes + packet.count > maxPendingOutputBytes
        if !wouldOverflow {
            pendingOutputBytes += packet.count
        }
        stateLock.unlock()
        if wouldOverflow {
            queue.async { [weak self] in self?.forceNextKeyframe = true }
            return
        }
        outputQueue.async { [weak self] in
            self?.writePacket(packet)
        }
    }
    
    private func extractAnnexB(from sampleBuffer: CMSampleBuffer) -> (data: Data, isKeyFrame: Bool)? {
        guard let formatDesc = CMSampleBufferGetFormatDescription(sampleBuffer) else { return nil }
        
        var isKeyFrame = true
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false) as? [[CFString: Any]],
           let first = attachments.first,
           let notSync = first[kCMSampleAttachmentKey_NotSync] as? Bool,
           notSync {
            isKeyFrame = false
        }
        
        var outputData = Data()
        let startCode = Data([0x00, 0x00, 0x00, 0x01])
        
        if isKeyFrame {
            var count = 0
            CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
                formatDesc,
                parameterSetIndex: 0,
                parameterSetPointerOut: nil,
                parameterSetSizeOut: nil,
                parameterSetCountOut: &count,
                nalUnitHeaderLengthOut: nil
            )
            for i in 0..<count {
                var ptr: UnsafePointer<UInt8>?
                var size = 0
                let st = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
                    formatDesc,
                    parameterSetIndex: i,
                    parameterSetPointerOut: &ptr,
                    parameterSetSizeOut: &size,
                    parameterSetCountOut: nil,
                    nalUnitHeaderLengthOut: nil
                )
                if st == noErr, let ptr = ptr, size > 0 {
                    outputData.append(startCode)
                    outputData.append(ptr, count: size)
                }
            }
        }
        
        guard let dataBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { return nil }
        var totalLength = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        let st = CMBlockBufferGetDataPointer(dataBuffer, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &totalLength, dataPointerOut: &dataPointer)
        guard st == noErr, let dataPointer = dataPointer else { return nil }
        
        var offset = 0
        let ptr = UnsafeRawPointer(dataPointer).assumingMemoryBound(to: UInt8.self)
        while offset < totalLength - 4 {
            let naluLength = Int(ptr[offset]) << 24 |
                             Int(ptr[offset + 1]) << 16 |
                             Int(ptr[offset + 2]) << 8 |
                             Int(ptr[offset + 3])
            offset += 4
            if offset + naluLength <= totalLength {
                outputData.append(startCode)
                outputData.append(ptr.advanced(by: offset), count: naluLength)
                offset += naluLength
            } else {
                break
            }
        }
        
        return (outputData, isKeyFrame)
    }
}

let environment = ProcessInfo.processInfo.environment
let encoderWidth = Int32(environment["FLY_STREAMER_WIDTH"] ?? "") ?? 1920
let encoderHeight = Int32(environment["FLY_STREAMER_HEIGHT"] ?? "") ?? 1080
let encoderFps = Int32(environment["FLY_STREAMER_FPS"] ?? "") ?? 60
let encoderBitrate = Int32(environment["FLY_STREAMER_BITRATE"] ?? "") ?? 4_500_000
let encoderDisplayName = environment["FLY_STREAMER_DISPLAY_NAME"] ?? ""
let encoder = ScreenEncoder(width: encoderWidth, height: encoderHeight, fps: encoderFps, bitrate: encoderBitrate, displayName: encoderDisplayName)
encoder.start()

signal(SIGINT) { _ in exit(0) }
signal(SIGTERM) { _ in exit(0) }

dispatchMain()
