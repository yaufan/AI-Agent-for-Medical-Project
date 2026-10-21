cmake_minimum_required(VERSION 3.16)
project(nodule_infer CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 指到 ONNX Runtime 官方 release 解壓後的資料夾（內含 include/ 與 lib/）
set(ONNXRUNTIME_DIR "" CACHE PATH "ONNX Runtime root (contains include/ and lib/)")
if(NOT ONNXRUNTIME_DIR)
  message(FATAL_ERROR "請用 -DONNXRUNTIME_DIR=<路徑> 指定 ONNX Runtime")
endif()

add_executable(nodule_infer nodule_infer.cpp)
target_include_directories(nodule_infer PRIVATE ${ONNXRUNTIME_DIR}/include)
find_library(ORT_LIB onnxruntime PATHS ${ONNXRUNTIME_DIR}/lib REQUIRED NO_DEFAULT_PATH)
target_link_libraries(nodule_infer PRIVATE ${ORT_LIB})
if(UNIX)
  set_target_properties(nodule_infer PROPERTIES BUILD_RPATH ${ONNXRUNTIME_DIR}/lib)
endif()
