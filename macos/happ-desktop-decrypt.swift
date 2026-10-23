// Private stdin/stdout bridge: plaintext stays in pipes and process memory.
// CryptoKit authenticates the complete database before releasing any plaintext.
import CryptoKit
import Foundation

struct Request: Decodable {
    let key: Data
    let nonce: Data
    let data: Data
    let tag: Data
}

do {
    let input = FileHandle.standardInput.readDataToEndOfFile()
    let request = try JSONDecoder().decode(Request.self, from: input)
    guard request.key.count == 16, request.nonce.count == 12, request.tag.count == 16 else {
        exit(1)
    }
    let box = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: request.nonce),
                                 ciphertext: request.data, tag: request.tag)
    let plaintext = try AES.GCM.open(box, using: SymmetricKey(data: request.key))
    FileHandle.standardOutput.write(plaintext)
} catch {
    // Never print keys, database bodies, or library exception descriptions.
    exit(1)
}
