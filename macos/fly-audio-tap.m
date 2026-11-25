#import <Foundation/Foundation.h>
#import <CoreAudio/CoreAudio.h>
#import <CoreAudio/CATapDescription.h>
#import <CoreAudio/AudioHardwareTapping.h>
#import <arpa/inet.h>

#import <AVFoundation/AVFoundation.h>
#import <opus/opus.h>
#import <sys/file.h>
#import <fcntl.h>
#import <unistd.h>
#import <signal.h>

static void fail(NSString *where, OSStatus status) {
    fprintf(stderr, "%s: %d\n", where.UTF8String, (int)status);
    exit(1);
}
static void check(NSString *where, OSStatus status) {
    if (status != noErr) fail(where, status);
}
int main(int argc, const char **argv) {
    @autoreleasepool {
        if ((argc != 2 && argc != 3) || (strcmp(argv[1], "client") && strcmp(argv[1], "both"))) return 2;
        BOOL pcmMode = argc == 3 && strcmp(argv[2], "pcm") == 0;
        // Only one system-audio capture across the two independent Native services.
        NSString *lock = [NSHomeDirectory() stringByAppendingPathComponent:@".local/share/fly-terminal/audio.lock"];
        int fd = open(lock.fileSystemRepresentation, O_CREAT|O_RDWR|O_NOFOLLOW, 0600);
        if (fd < 0 || flock(fd, LOCK_EX|LOCK_NB) != 0) fail(@"audio_already_in_use", -1);
        // EOF on the parent's pipe also terminates capture after an abrupt server exit.
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            char c; while (read(STDIN_FILENO, &c, 1) > 0) {}
            exit(0);
        });
        CATapDescription *desc = [[CATapDescription alloc] initStereoGlobalTapButExcludeProcesses:@[]];
        desc.name = @"Fly Terminal System Audio";
        desc.privateTap = YES;
        desc.muteBehavior = strcmp(argv[1], "client") == 0 ? CATapMutedWhenTapped : CATapUnmuted;
        AudioObjectID tap = kAudioObjectUnknown;
        check(@"create_tap", AudioHardwareCreateProcessTap(desc, &tap));
        AudioStreamBasicDescription asbd = {0};
        UInt32 size = sizeof(asbd);
        AudioObjectPropertyAddress addr = {kAudioTapPropertyFormat,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
        check(@"tap_format", AudioObjectGetPropertyData(tap, &addr, 0, NULL, &size, &asbd));
        AVAudioFormat *input = [[AVAudioFormat alloc] initWithStreamDescription:&asbd];
        AVAudioFormat *output = [[AVAudioFormat alloc] initWithCommonFormat:AVAudioPCMFormatFloat32 sampleRate:48000 channels:2 interleaved:YES];
        AVAudioConverter *converter = [[AVAudioConverter alloc] initFromFormat:input toFormat:output];
        if (!converter) fail(@"audio_converter", -1);
        int error = 0;
        OpusEncoder *encoder = opus_encoder_create(48000, 2, OPUS_APPLICATION_AUDIO, &error);
        if (!encoder || error) fail(@"opus_encoder", error);
        opus_encoder_ctl(encoder, OPUS_SET_BITRATE(128000));
        NSString *uid = [[NSUUID UUID] UUIDString];
        NSDictionary *spec = @{
            @kAudioAggregateDeviceNameKey:@"Fly Terminal Audio",
            @kAudioAggregateDeviceUIDKey:uid,
            @kAudioAggregateDeviceIsPrivateKey:@YES,
            @kAudioAggregateDeviceTapAutoStartKey:@YES,
            @kAudioAggregateDeviceTapListKey:@[@{@kAudioSubTapUIDKey:desc.UUID.UUIDString, @kAudioSubTapDriftCompensationKey:@YES}]
        };
        AudioObjectID device = kAudioObjectUnknown;
        check(@"create_aggregate", AudioHardwareCreateAggregateDevice((__bridge CFDictionaryRef)spec, &device));
        dispatch_queue_t queue = dispatch_queue_create("fly.audio.capture", DISPATCH_QUEUE_SERIAL);
        __block NSMutableData *pending = [NSMutableData data];
        AudioDeviceIOProcID proc = NULL;
        check(@"create_ioproc", AudioDeviceCreateIOProcIDWithBlock(&proc, device, queue,
            ^(const AudioTimeStamp *now, const AudioBufferList *inData, const AudioTimeStamp *inTime, AudioBufferList *outData, const AudioTimeStamp *outTime) {
                if (!inData || !inData->mNumberBuffers || !inData->mBuffers[0].mData || !asbd.mBytesPerFrame) return;
                AVAudioFrameCount frames = inData->mBuffers[0].mDataByteSize / asbd.mBytesPerFrame;
                if (!frames) return;
                AVAudioPCMBuffer *src = [[AVAudioPCMBuffer alloc] initWithPCMFormat:input frameCapacity:frames];
                src.frameLength = frames;
                AudioBufferList *dst = src.mutableAudioBufferList;
                if (dst->mNumberBuffers != inData->mNumberBuffers) return;
                for (UInt32 i=0; i<dst->mNumberBuffers; i++) {
                    if (dst->mBuffers[i].mDataByteSize < inData->mBuffers[i].mDataByteSize) return;
                    memcpy(dst->mBuffers[i].mData, inData->mBuffers[i].mData, inData->mBuffers[i].mDataByteSize);
                }
                AVAudioFrameCount cap = (AVAudioFrameCount)ceil(frames*48000.0/asbd.mSampleRate)+64;
                AVAudioPCMBuffer *pcm = [[AVAudioPCMBuffer alloc] initWithPCMFormat:output frameCapacity:cap];
                __block BOOL supplied = NO;
                NSError *conversionError = nil;
                AVAudioConverterOutputStatus result = [converter convertToBuffer:pcm error:&conversionError withInputFromBlock:^AVAudioBuffer *(AVAudioPacketCount n, AVAudioConverterInputStatus *status) {
                    if (supplied) { *status=AVAudioConverterInputStatus_NoDataNow; return nil; }
                    supplied=YES; *status=AVAudioConverterInputStatus_HaveData; return src;
                }];
                if (result == AVAudioConverterOutputStatus_Error || !pcm.frameLength) return;
                [pending appendBytes:pcm.audioBufferList->mBuffers[0].mData length:pcm.frameLength*2*sizeof(float)];
                const NSUInteger frameBytes = 960*2*sizeof(float);
                while (pending.length >= frameBytes) {
                    unsigned char encoded[3840];
                    int n;
                    if (pcmMode) {
                        const float *samples = pending.bytes;
                        for (int i=0;i<1920;i++) {
                            float value = isfinite(samples[i]) ? fmaxf(-1, fminf(1, samples[i])) : 0;
                            uint16_t v = (uint16_t)(int16_t)lrintf(value * 32767);
                            encoded[2*i] = v & 255; encoded[2*i+1] = v >> 8;
                        }
                        n = 3840;
                    } else n = opus_encode_float(encoder, pending.bytes, 960, encoded, 1275);
                    [pending replaceBytesInRange:NSMakeRange(0,frameBytes) withBytes:NULL length:0];
                    if (n <= 0) continue;
                    uint16_t length = htons((uint16_t)n);
                    if (fwrite(&length,1,2,stdout)!=2 || fwrite(encoded,1,n,stdout)!=(size_t)n || fflush(stdout)!=0) exit(0);
                }
            }));
        check(@"start_tap", AudioDeviceStart(device, proc));
        fprintf(stderr,"audio_ready\n");
        // Private tap and aggregate are reclaimed by Core Audio on process exit.
        dispatch_main();
    }
}
