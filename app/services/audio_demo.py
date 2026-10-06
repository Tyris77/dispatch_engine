import io
import math
import struct
import wave
from typing import Any, Dict, List


def generate_synthesized_demo_wav(duration_seconds: int = 32, sample_rate: int = 8000) -> bytes:
    """
    Generates a realistic 32-second telephone audio simulation in valid WAV format.
    Includes:
      - 00:00 - 00:00.4: Sub-second phone connection chime & DTMF tone
      - 00:00.4 - 00:04.0: Agitated customer speech rhythm (Mrs. Higgins)
      - 00:04.0 - 00:04.5: Calming audio transition tone
      - 00:04.5 - 00:18.0: Clear, reassuring AI receptionist speech rhythm (Danielle)
      - 00:18.0 - 00:18.5: Priority technician dispatch audio chime
      - 00:18.5 - 00:32.0: Danielle's confirmation & live arrival ETA dispatch rhythm
    """
    total_samples = int(duration_seconds * sample_rate)
    buf = io.BytesIO()

    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)

        samples = []
        for i in range(total_samples):
            t = i / sample_rate
            sample_val = 0.0

            # 1. Connection tone (0.0 to 0.4s)
            if t < 0.4:
                # Ring chime (440Hz + 480Hz dual tone)
                sample_val = 0.25 * math.sin(2 * math.pi * 440 * t) + 0.25 * math.sin(2 * math.pi * 480 * t)
            # Short click at 0.4s (pickup)
            elif 0.4 <= t < 0.45:
                sample_val = 0.4 * (1.0 if (i % 4 == 0) else -1.0) * math.exp(-20 * (t - 0.4))
            # 2. Mrs. Higgins speaking (0.45s to 4.0s)
            elif 0.45 <= t < 4.0:
                # Modulated voice formants (220Hz fundamental with 440Hz and 880Hz harmonics + speech syllable cadence)
                cadence = 0.5 + 0.5 * math.sin(2 * math.pi * 3.5 * t)  # Syllable rate ~3.5Hz
                formant = (
                    0.3 * math.sin(2 * math.pi * 260 * t)
                    + 0.15 * math.sin(2 * math.pi * 520 * t)
                    + 0.1 * math.sin(2 * math.pi * 780 * t)
                )
                sample_val = cadence * formant
            # 3. Chime transition (4.0s to 4.5s)
            elif 4.0 <= t < 4.5:
                sample_val = 0.15 * math.sin(2 * math.pi * 587.33 * t) * math.exp(-4 * (t - 4.0))
            # 4. Danielle AI Receptionist speaking (4.5s to 18.0s)
            elif 4.5 <= t < 18.0:
                # Calmer, crisp synthesized cadence (~4Hz speech rhythm)
                cadence = 0.55 + 0.45 * math.sin(2 * math.pi * 4.0 * t)
                formant = (
                    0.32 * math.sin(2 * math.pi * 220 * t)
                    + 0.18 * math.sin(2 * math.pi * 440 * t)
                    + 0.08 * math.sin(2 * math.pi * 880 * t)
                )
                sample_val = cadence * formant
            # 5. Priority Dispatch Chime (18.0s to 18.5s)
            elif 18.0 <= t < 18.5:
                # Upbeat affirmative chime (880Hz + 1174Hz)
                sample_val = 0.2 * math.sin(2 * math.pi * 880 * t) + 0.15 * math.sin(2 * math.pi * 1174.66 * t)
            # 6. Danielle confirmation & ETA dispatch (18.5s to 32.0s)
            elif 18.5 <= t < 32.0:
                cadence = 0.55 + 0.45 * math.sin(2 * math.pi * 4.2 * t)
                formant = (
                    0.30 * math.sin(2 * math.pi * 230 * t)
                    + 0.16 * math.sin(2 * math.pi * 460 * t)
                    + 0.08 * math.sin(2 * math.pi * 920 * t)
                )
                sample_val = cadence * formant

            # Gentle background carrier comfort noise
            noise = 0.015 * ((hash(str(i)) % 100) / 100.0 - 0.5)
            sample_val += noise

            # Clamp and convert to 16-bit PCM integer
            sample_int = int(max(-1.0, min(1.0, sample_val)) * 32767)
            samples.append(struct.pack("<h", sample_int))

        wav_file.writeframes(b"".join(samples))

    return buf.getvalue()


def get_sample_call_scenario() -> Dict[str, Any]:
    """
    Returns realistic 2:15 AM homeowner burst-pipe flood call scenario
    with timestamped dialogue between 'Mrs. Higgins' and AI Receptionist 'Danielle'.
    """
    return {
        "call_id": "call_2026_demo_0215am",
        "title": "2:15 AM Emergency Burst Pipe & Ceiling Flood",
        "timestamp": "2:15 AM EST (After-Hours Emergency)",
        "caller_name": "Mrs. Eleanor Higgins",
        "caller_phone": "+1 (202) 555-0194",
        "caller_address": "4820 Wisconsin Ave NW, Washington, DC",
        "agent_name": "Danielle",
        "agent_role": "AI Emergency Receptionist",
        "duration_seconds": 32,
        "audio_url": "/api/v1/demo/sample-audio",
        "metrics": {
            "pickup_time": "0.4s (Sub-second answer)",
            "urgency_level": "EMERGENCY (0.99 Score)",
            "estimated_ticket": "$1,250",
            "dispatch_time": "32 seconds from ring to technician lock",
            "assigned_tech": "Carlos Gomez (Truck #09)",
            "tech_eta": "18 minutes",
        },
        "turns": [
            {
                "index": 1,
                "start_seconds": 0.0,
                "end_seconds": 4.0,
                "speaker": "Mrs. Higgins",
                "role": "Homeowner (Panicked)",
                "avatar": "👵",
                "text": "Help! There is water pouring through my living room ceiling right now! The pipe burst in the upstairs bathroom and it's flooding everywhere!",
                "highlight": "Active emergency report (basement ceiling leak)",
            },
            {
                "index": 2,
                "start_seconds": 4.0,
                "end_seconds": 18.0,
                "speaker": "Danielle",
                "role": "AI Receptionist",
                "avatar": "🎙️",
                "text": "I'm right here with you, Mrs. Higgins. Please shut off your main water valve if it is safe to do so. Our emergency dispatch fee is $189 and our on-call master technician is ready. I just sent an instant photo upload link to your phone so you can show our team the leak while they drive.",
                "highlight": "Calms customer, quotes emergency fee, triggers instant photo scanner",
            },
            {
                "index": 3,
                "start_seconds": 18.0,
                "end_seconds": 32.0,
                "speaker": "Danielle",
                "role": "AI Receptionist",
                "avatar": "🚨",
                "text": "Master Technician Carlos Gomez in Truck #09 has accepted your priority dispatch. His live GPS arrival link has been texted to you—he is 18 minutes away. Hang tight, help is en route!",
                "highlight": "Assigns on-call master technician with live GPS tracking",
            },
        ],
    }
