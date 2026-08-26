import Foundation
import ScreenCaptureKit
import VideoToolbox
import CoreVideo
import CoreMedia
import CoreGraphics
import IOKit.pwr_mgt

final class ScreenEncoder: NSObject, SCStreamOutput, SCStreamDelegate {
    private var scStream: SCStream?
    private var compressionSession: VTCompressionSession?
    private var frameIndex: Int64 = 0
    private var forceNextKeyframe = true
    private let targetWidth: Int32
    private let targetHeight: Int32
    private let fps: Int32
    private let bitrate: Int32
    private let queue = DispatchQueue(label: "ai.kruspe.fly-terminal.encoder", qos: .userInteractive)
    private let outHandle = FileHandle.standardOutput
    private var socketFD: Int32 = -1
    private var powerAssertionID: IOPMAssertionID = 0
    private var isCapturing = false
    
    init(width: Int32 = 1920, height: Int32 = 1080, fps: Int32 = 60, bitrate: Int32 = 4_500_000) {
        self.targetWidth = width
        self.targetHeight = height
        self.fps = fps
        self.bitrate = bitrate
        super.init()
        connectUnixSocket()
    }
    
    private func connectUnixSocket() {
        let sockPath = "/tmp/fly-mac-stream.sock"
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
        Task {
            await startCaptureLoop()
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
                guard let display = content.displays.first else {
                    fputs("[Encoder] No active displays found. Retrying in 2s...\n", stderr)
                    try await Task.sleep(nanoseconds: 2_000_000_000)
                    continue
                }
                
                fputs("[Encoder] Found display \(display.displayID): \(display.width)x\(display.height)\n", stderr)
                setupVideoToolbox()
                
                let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
                let config = SCStreamConfiguration()
                config.width = Int(targetWidth)
                config.height = Int(targetHeight)
                config.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(fps))
                config.showsCursor = true
                config.pixelFormat = kCVPixelFormatType_32BGRA
                config.queueDepth = 5
                
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
    
    private func setupVideoToolbox() {
        if let existing = compressionSession {
            VTCompressionSessionInvalidate(existing)
            compressionSession = nil
        }
        
        let callback: VTCompressionOutputCallback = { refCon, _, status, _, sampleBuffer in
            guard status == noErr, let sampleBuffer = sampleBuffer, let refCon = refCon else { return }
            let enc = Unmanaged<ScreenEncoder>.fromOpaque(refCon).takeUnretainedValue()
            enc.outputFrame(sampleBuffer: sampleBuffer)
        }
        
        var session: VTCompressionSession?
        let status = VTCompressionSessionCreate(
            allocator: kCFAllocatorDefault,
            width: targetWidth,
            height: targetHeight,
            codecType: kCMVideoCodecType_H264,
            encoderSpecification: nil,
            imageBufferAttributes: nil,
            compressedDataAllocator: nil,
            outputCallback: callback,
            refcon: Unmanaged.passUnretained(self).toOpaque(),
            compressionSessionOut: &session
        )
        
        guard status == noErr, let session = session else {
            fputs("[Encoder] VTCompressionSessionCreate failed: \(status)\n", stderr)
            return
        }
        
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_RealTime, value: kCFBooleanTrue!)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_ProfileLevel, value: kVTProfileLevel_H264_Main_AutoLevel)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_AverageBitRate, value: bitrate as CFNumber)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_ExpectedFrameRate, value: fps as CFNumber)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_MaxKeyFrameInterval, value: fps as CFNumber)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_AllowFrameReordering, value: kCFBooleanFalse!)
        VTCompressionSessionPrepareToEncodeFrames(session)
        self.compressionSession = session
    }
    
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, let pixelBuffer = sampleBuffer.imageBuffer, let session = compressionSession else { return }
        frameIndex += 1
        let pts = CMTime(value: frameIndex, timescale: CMTimeScale(fps))
        let duration = CMTime(value: 1, timescale: CMTimeScale(fps))
        var props: [CFString: Any]? = nil
        if forceNextKeyframe || (frameIndex % Int64(fps * 2) == 0) {
            props = [kVTEncodeFrameOptionKey_ForceKeyFrame: true]
            forceNextKeyframe = false
        }
        VTCompressionSessionEncodeFrame(
            session,
            imageBuffer: pixelBuffer,
            presentationTimeStamp: pts,
            duration: duration,
            frameProperties: props as CFDictionary?,
            sourceFrameRefcon: nil,
            infoFlagsOut: nil
        )
    }
    
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fputs("[Encoder] Stream stopped: \(error). Reconnecting...\n", stderr)
        isCapturing = false
        Task {
            await startCaptureLoop()
        }
    }
    
    private func outputFrame(sampleBuffer: CMSampleBuffer) {
        guard let (h264Data, isKeyFrame) = extractAnnexB(from: sampleBuffer) else { return }
        
        let payloadLen = UInt32(1 + 8 + h264Data.count)
        var lenBig = payloadLen.bigEndian
        var flags: UInt8 = isKeyFrame ? 0x01 : 0x00
        var nowMs = Int64(Date().timeIntervalSince1970 * 1000).bigEndian
        
        var packet = Data(capacity: 4 + Int(payloadLen))
        withUnsafeBytes(of: &lenBig) { packet.append(contentsOf: $0) }
        packet.append(&flags, count: 1)
        withUnsafeBytes(of: &nowMs) { packet.append(contentsOf: $0) }
        packet.append(h264Data)
        
        if socketFD < 0 {
            connectUnixSocket()
        }
        
        if socketFD >= 0 {
            packet.withUnsafeBytes { raw in
                if let base = raw.baseAddress {
                    let written = write(socketFD, base, raw.count)
                    if written <= 0 {
                        close(socketFD)
                        socketFD = -1
                    }
                }
            }
        } else {
            try? outHandle.write(contentsOf: packet)
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

let encoder = ScreenEncoder()
encoder.start()

signal(SIGINT) { _ in exit(0) }
signal(SIGTERM) { _ in exit(0) }

dispatchMain()
