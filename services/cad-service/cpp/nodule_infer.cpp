// 以 ONNX Runtime C++ API 執行 P1 的 3D CNN（降誤報模型）。
// 用途：示範產線／設備端常見的 C++ 推論整合；前處理（重取樣、候選點）仍在 Python 端。
//
// 輸入檔格式（little-endian）：int32 N，接著 N×32×32×32 個 float32（已正規化到 [0,1] 的區塊）
// 輸出：每行一個機率；耗時印在 stderr。
//
// 用法：nodule_infer <model.onnx> <patches.bin> [threads]
#include <onnxruntime_cxx_api.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {
constexpr int64_t kPatch = 32;
constexpr int64_t kVoxels = kPatch * kPatch * kPatch;
constexpr int64_t kBatch = 64;

std::vector<float> ReadPatches(const std::string& path, int32_t& n) {
  std::ifstream f(path, std::ios::binary);
  if (!f) throw std::runtime_error("cannot open " + path);
  f.read(reinterpret_cast<char*>(&n), sizeof(n));
  if (n < 0) throw std::runtime_error("bad patch count");
  std::vector<float> data(static_cast<size_t>(n) * kVoxels);
  f.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size() * sizeof(float)));
  if (!f) throw std::runtime_error("file shorter than header says");
  return data;
}
}  // namespace

int main(int argc, char** argv) {
  if (argc < 3) {
    std::cerr << "usage: " << argv[0] << " <model.onnx> <patches.bin> [threads]\n";
    return 2;
  }
  try {
    const int threads = argc > 3 ? std::stoi(argv[3]) : 4;
    int32_t n = 0;
    std::vector<float> patches = ReadPatches(argv[2], n);

    Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "nodule_infer");
    Ort::SessionOptions opts;
    opts.SetIntraOpNumThreads(threads);
    opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    auto t0 = std::chrono::steady_clock::now();
    Ort::Session session(env, argv[1], opts);
    auto t1 = std::chrono::steady_clock::now();

    Ort::AllocatorWithDefaultOptions alloc;
    auto in_name = session.GetInputNameAllocated(0, alloc);
    auto out_name = session.GetOutputNameAllocated(0, alloc);
    const char* in_names[] = {in_name.get()};
    const char* out_names[] = {out_name.get()};
    auto mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);

    std::vector<float> probs;
    probs.reserve(n);
    for (int64_t start = 0; start < n; start += kBatch) {
      const int64_t b = std::min<int64_t>(kBatch, n - start);
      std::vector<int64_t> shape{b, 1, kPatch, kPatch, kPatch};
      Ort::Value input = Ort::Value::CreateTensor<float>(
          mem, patches.data() + start * kVoxels, static_cast<size_t>(b * kVoxels), shape.data(), shape.size());
      auto out = session.Run(Ort::RunOptions{nullptr}, in_names, &input, 1, out_names, 1);
      const float* logit = out[0].GetTensorData<float>();
      for (int64_t i = 0; i < b; ++i) probs.push_back(1.0f / (1.0f + std::exp(-logit[i])));
    }
    auto t2 = std::chrono::steady_clock::now();

    for (float p : probs) std::cout << p << "\n";
    auto ms = [](auto a, auto b) { return std::chrono::duration<double, std::milli>(b - a).count(); };
    std::cerr << "load_ms=" << ms(t0, t1) << " infer_ms=" << ms(t1, t2) << " n=" << n
              << " threads=" << threads << "\n";
  } catch (const std::exception& e) {
    std::cerr << "error: " << e.what() << "\n";
    return 1;
  }
  return 0;
}
