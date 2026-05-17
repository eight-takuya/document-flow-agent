// vision_ocr.swift
// macOS Vision framework を使った日本語/英語 OCR ツール
// Usage: vision_ocr <image_path>
// コンパイル: swiftc vision_ocr.swift -o vision_ocr

import Vision
import AppKit

guard CommandLine.arguments.count > 1 else {
    fputs("Usage: vision_ocr <image_path>\n", stderr)
    exit(1)
}

let path = CommandLine.arguments[1]
let url = URL(fileURLWithPath: path)

guard FileManager.default.fileExists(atPath: path) else {
    fputs("File not found: \(path)\n", stderr)
    exit(1)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ja-JP", "en-US"]
request.usesLanguageCorrection = true
request.minimumTextHeight = 0.01

let handler = VNImageRequestHandler(url: url, options: [:])
do {
    try handler.perform([request])
} catch {
    fputs("OCR error: \(error)\n", stderr)
    exit(1)
}

if let results = request.results {
    for observation in results {
        if let candidate = observation.topCandidates(1).first {
            print(candidate.string)
        }
    }
}
