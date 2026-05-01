"""
快速验证脚本：在终端打印实时转录结果
用法：python test_streaming.py

第一次运行会下载约 2GB 模型文件，请耐心等待。
"""
import sys
import numpy as np
import sounddevice as sd
from funasr import AutoModel

print("Loading streaming model...")
model = AutoModel(
    model="paraformer-zh-streaming",
    device="cuda:0",
    disable_update=True,
)
print("[OK] Model loaded\n")
print("=" * 60)
print("开始说话（按 Ctrl+C 退出）")
print("=" * 60 + "\n")

chunk_size = [0, 10, 5]  # 600ms
sample_rate = 16000
chunk_samples = int(sample_rate * 0.6)
cache = {}

def callback(indata, frames, time_info, status):
    if status:
        print(f"[!] {status}", file=sys.stderr)
    audio = indata[:, 0].astype(np.float32)
    res = model.generate(
        input=audio,
        cache=cache,
        is_final=False,
        chunk_size=chunk_size,
        encoder_chunk_look_back=4,
        decoder_chunk_look_back=1,
    )
    if res and res[0].get("text"):
        print(res[0]["text"], end="", flush=True)

try:
    with sd.InputStream(
        callback=callback,
        channels=1,
        samplerate=sample_rate,
        blocksize=chunk_samples,
        dtype="float32",
    ):
        while True:
            sd.sleep(1000)
except KeyboardInterrupt:
    print("\n\n[OK] 退出")
