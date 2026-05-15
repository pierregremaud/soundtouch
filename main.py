#!/usr/bin/env python3

import time
import requests
import websocket

# -------------------------
# Configuration
# -------------------------

SOUNDTOUCH_IP = "192.168.0.160"

PRESETS = {
    "1": {
        "name": "RTS La Première",
        "url": "http://stream.srg-ssr.ch/m/la-1ere/mp3_128",
    },
    "2": {
        "name": "RTS Espace 2",
        "url": "http://stream.srg-ssr.ch/m/espace-2/mp3_128",
    },
    "3": {
        "name": "RTS Couleur 3",
        "url": "http://stream.srg-ssr.ch/m/couleur3/mp3_128",
    },
}

COOLDOWN_SECONDS = 5

# Important after SoundTouch wake-up
WAKEUP_SETTLE_SECONDS = 3
DELAY_BEFORE_PLAY_SECONDS = 2

# Retry once if Bose reports INVALID_SOURCE
RETRY_DELAY_SECONDS = 4
MAX_RETRIES = 0

WS_URL = f"ws://{SOUNDTOUCH_IP}:8080"
AVTRANSPORT_URL = f"http://{SOUNDTOUCH_IP}:8091/AVTransport/Control"

last_trigger_time = 0
last_requested_preset = None
retry_count = 0


# -------------------------
# AVTransport / SOAP
# -------------------------

def post_avtransport(action, body):
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"',
    }

    try:
        response = requests.post(
            AVTRANSPORT_URL,
            headers=headers,
            data=body,
            timeout=8,
        )

        print(f"{action}: HTTP {response.status_code}", flush=True)

        if response.status_code >= 400:
            print(response.text, flush=True)

        return response

    except requests.RequestException as e:
        print(f"{action}: request failed: {e}", flush=True)
        return None


def set_avtransport_uri(stream_url):
    body = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <CurrentURI>{stream_url}</CurrentURI>
      <CurrentURIMetaData></CurrentURIMetaData>
    </u:SetAVTransportURI>
  </s:Body>
</s:Envelope>"""

    return post_avtransport("SetAVTransportURI", body)


def play():
    body = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:Play xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <Speed>1</Speed>
    </u:Play>
  </s:Body>
</s:Envelope>"""

    return post_avtransport("Play", body)


def play_stream(preset_id, is_retry=False):
    global last_requested_preset, retry_count

    preset = PRESETS[preset_id]

    if not is_retry:
        retry_count = 0

    last_requested_preset = preset_id

    print(f"Preset {preset_id}: {preset['name']}", flush=True)
    print(f"Streaming: {preset['url']}", flush=True)

    if not is_retry:
        print(f"Waiting {WAKEUP_SETTLE_SECONDS}s for SoundTouch to settle...", flush=True)
        time.sleep(WAKEUP_SETTLE_SECONDS)

    set_avtransport_uri(preset["url"])

#    time.sleep(DELAY_BEFORE_PLAY_SECONDS)

#    play()

    print("Done.", flush=True)


# -------------------------
# WebSocket event handling
# -------------------------

def get_preset_id_from_message(message):
    for preset_id in PRESETS:
        if f'<preset id="{preset_id}"' in message:
            return preset_id

    return None


def handle_invalid_source():
    global retry_count, last_requested_preset

    if last_requested_preset is None:
        print("INVALID_SOURCE received, but no preset is pending.", flush=True)
        return

    if retry_count >= MAX_RETRIES:
        print("INVALID_SOURCE received; max retry reached.", flush=True)
        last_requested_preset = None
        return

    retry_count += 1
    preset_id = last_requested_preset

    print(
        f"INVALID_SOURCE received. Retrying preset {preset_id} "
        f"in {RETRY_DELAY_SECONDS}s... ({retry_count}/{MAX_RETRIES})",
        flush=True,
    )

    time.sleep(RETRY_DELAY_SECONDS)
    play_stream(preset_id, is_retry=True)


def on_open(ws):
    print(f"[CONNECTED] {WS_URL}", flush=True)


def on_message(ws, message):
    global last_trigger_time

    preset_id = get_preset_id_from_message(message)

    if preset_id in PRESETS:
        now = time.time()

        if now - last_trigger_time < COOLDOWN_SECONDS:
            print("Ignored duplicate preset event.", flush=True)
            return

        last_trigger_time = now

        print(f"Preset {preset_id} detected.", flush=True)
        play_stream(preset_id)
        return

    if 'source="INVALID_SOURCE"' in message:
        handle_invalid_source()
        return

    if 'source="UPNP"' in message and "location=" in message:
        print("UPnP now playing update.", flush=True)
        return

    if "<userActivityUpdate" in message:
        return


def on_error(ws, error):
    print(f"[ERROR] {error}", flush=True)


def on_close(ws, close_status_code, close_msg):
    print(f"[DISCONNECTED] {close_status_code} {close_msg}", flush=True)


# -------------------------
# Main loop
# -------------------------

def main():
    while True:
        print(f"Connecting to {WS_URL}", flush=True)

        ws = websocket.WebSocketApp(
            WS_URL,
            subprotocols=["gabbo"],
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        ws.run_forever(
            ping_interval=None,
            origin=f"http://{SOUNDTOUCH_IP}",
        )

        print("WebSocket disconnected. Reconnecting in 5 seconds...", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
