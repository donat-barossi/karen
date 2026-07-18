"""
PlatformIO extra script: impacchetta i modelli ESP-SR e li flasha
sulla partizione 'model' (offset 0x210000).
"""
import os
import subprocess
import sys

Import("env")  # noqa: F821

MODEL_OFFSET = "0x210000"


def _pack_srmodels(env):
    project_dir = env["PROJECT_DIR"]
    build_dir = env["BUILD_DIR"]
    pioenv = env["PIOENV"]

    sdkconfig = os.path.join(project_dir, f"sdkconfig.{pioenv}")
    if not os.path.exists(sdkconfig):
        sdkconfig = os.path.join(project_dir, "sdkconfig")

    esp_sr = os.path.join(project_dir, "managed_components", "espressif__esp-sr")
    movemodel = os.path.join(esp_sr, "model", "movemodel.py")

    if not os.path.exists(movemodel):
        print(f"[pack_srmodels] WARN: {movemodel} non trovato")
        return None

    print("[pack_srmodels] Impacchetto modelli wake word…")
    ret = subprocess.call([
        sys.executable, movemodel,
        "-d1", sdkconfig,
        "-d2", esp_sr,
        "-d3", build_dir,
    ])
    if ret != 0:
        env.Exit(1)

    srmodels_bin = os.path.join(build_dir, "srmodels", "srmodels.bin")
    if not os.path.exists(srmodels_bin):
        print("[pack_srmodels] ERRORE: srmodels.bin non generato")
        env.Exit(1)

    size_kb = os.path.getsize(srmodels_bin) / 1024
    print(f"[pack_srmodels] OK: srmodels.bin ({size_kb:.1f} KB)")
    return srmodels_bin


def flash_srmodels(source, target, env):
    srmodels_bin = _pack_srmodels(env)
    if not srmodels_bin:
        return

    upload_port = env.subst("$UPLOAD_PORT")
    esptool = env.subst("$UPLOADER")
    cmd = [
        sys.executable, esptool,
        "--chip", "esp32s3",
        "--port", upload_port,
        "--baud", env.subst("$UPLOAD_SPEED"),
        "write_flash",
        MODEL_OFFSET, srmodels_bin,
    ]
    print(f"[pack_srmodels] Flash modello @ {MODEL_OFFSET}…")
    ret = subprocess.call(cmd)
    if ret != 0:
        env.Exit(1)
    print("[pack_srmodels] Modello wake word flashato")


env.AddPostAction("upload", flash_srmodels)
