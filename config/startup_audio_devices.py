import os
import sys
import json

import sounddevice as sd
from dotenv import load_dotenv

# Add the root directory to sys.path
root_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_directory not in sys.path:
    sys.path.insert(0, root_directory)

from my_modules.my_logging import create_logger

chatzilla_device_hostapi_name = "Windows WASAPI"

logger = create_logger(
    debug_level='INFO', 
    logger_name="logger_startup_audio"
)

def get_wasapi_microphones(output_filepath=None):
    """
    Retrieve a flat list of WASAPI devices that have microphone capabilities (max_input_channels > 0).
    Optionally save all WASAPI devices to a JSON file.

    Args:
        output_filepath (str, optional): Path to save all WASAPI devices as a JSON file.
    
    Returns:
        list[dict]: A list of dictionaries describing available WASAPI microphone devices.
    """
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        wasapi_index = next(
            (i for i, api in enumerate(hostapis) if api["name"] == chatzilla_device_hostapi_name),
            None
        )
    except Exception as e:
        logger.error(f"Error querying sound devices: {e}")
        return []

    if wasapi_index is None:
        logger.error(f"WASAPI Host API '{chatzilla_device_hostapi_name}' not found.")
        return []

    # Collect all WASAPI devices
    wasapi_devices = [
        {
            "index": idx,
            "name": device["name"],
            "hostapi": chatzilla_device_hostapi_name,
            "max_input_channels": device["max_input_channels"],
            "max_output_channels": device["max_output_channels"],
            "default_samplerate": device["default_samplerate"],
        }
        for idx, device in enumerate(devices) if device["hostapi"] == wasapi_index
    ]

    # Save all WASAPI devices to JSON if output_filepath is provided
    if output_filepath:
        try:
            with open(output_filepath, "w", encoding="utf-8") as json_file:
                json.dump(wasapi_devices, json_file, indent=4)
            logger.info(f"[get_wasapi_microphones] WASAPI devices saved to {output_filepath}")
        except Exception as e:
            logger.error(f"[get_wasapi_microphones] Failed to save WASAPI devices to JSON: {e}")

    # Filter for microphones
    microphones = [device for device in wasapi_devices if device["max_input_channels"] > 0]

    logger.debug(f"[get_wasapi_microphones] Discovered mic devices: {microphones}")
    return microphones

def validate_device(device_name, case_insensitive=False):
    """
    Checks if 'device_name' is among the available WASAPI microphones.
    Optionally does case-insensitive matching.

    Args:
        device_name (str): The name of the device to validate.
        case_insensitive (bool): Whether to ignore case differences.

    Returns:
        bool: True if the device is found, False otherwise.
    """    
    #Ensure output_filepath directory exists
    output_filepath = r'.\data\botears\detected_wasapi_audio_devices.json'
    if not os.path.exists(os.path.dirname(output_filepath)):
        os.makedirs(os.path.dirname(output_filepath), exist_ok=True)
        
    microphones = get_wasapi_microphones(output_filepath=output_filepath)
    if case_insensitive:
        device_name = device_name.strip().lower()
        mic_names = [mic["name"].strip().lower() for mic in microphones]
    else:
        device_name = device_name.strip()
        mic_names = [mic["name"].strip() for mic in microphones]

    logger.info(f"[validate_device] Checking '{device_name}' against microphone names: {mic_names}")
    return device_name in mic_names

def append_or_update_env(env_file_path, key, value):
    """
    Update or append key=value in the .env file (unquoted).
    """
    if not os.path.exists(env_file_path):
        os.makedirs(os.path.dirname(env_file_path), exist_ok=True)
        with open(env_file_path, "w") as f:
            f.write(f"{key}={value}\n")
        return

    lines = []
    found_key = False
    with open(env_file_path, "r") as f:
        for line in f:
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}\n")
                found_key = True
            else:
                lines.append(line)
    if not found_key:
        lines.append(f"{key}={value}\n")

    with open(env_file_path, "w") as f:
        f.writelines(lines)

def ensure_audio_device_selected(env_file_path="./config/.env", device_env_var="CHATZILLA_MIC_DEVICE_NAME"):
    """
    Ensure a valid WASAPI microphone is selected, either from the .env file or via user input.
    Args:
        env_file_path (str): Path to the .env file.
        device_env_var (str): The environment variable key storing the microphone name.
    """
    logger.info(f"[ensure_audio_device_selected] Loading environment from '{env_file_path}'")
    load_dotenv(env_file_path)

    chosen_device = os.getenv(device_env_var, "").strip()
    if chosen_device:
        logger.info(f"[ensure_audio_device_selected] Found '{device_env_var}' in .env with value: '{chosen_device}'")
    else:
        logger.info(f"[ensure_audio_device_selected] No existing '{device_env_var}' found in .env.")

    # 1. If chosen_device is set, check if it's valid. 
    if chosen_device:
        if validate_device(chosen_device, case_insensitive=False):
            logger.info(f"Device '{chosen_device}' is valid. Skipping prompt.")
            return  # <--- EARLY RETURN
        else:
            # Possibly the device is gone or mismatch in name
            logger.warning(
                f"[ensure_audio_device_selected] The device '{chosen_device}' was not found "
                "among the available WASAPI microphones. Prompting user now."
            )

    # 2. Prompt user for a microphone, if not found or was invalid
    microphones = get_wasapi_microphones()
    if not microphones:
        logger.error("[ensure_audio_device_selected] No WASAPI microphone devices found. Exiting.")
        raise RuntimeError("No WASAPI microphone devices are available.")

    print("\nWASAPI Microphone Devices:")
    for i, mic in enumerate(microphones):
        print(f"[{i}] {mic['name']} (In={mic['max_input_channels']}, Out={mic['max_output_channels']})")

    try:
        user_index = int(input("\nEnter the number of the device you want to use: "))
        new_device = microphones[user_index]["name"]
    except (ValueError, IndexError) as e:
        logger.error(f"[ensure_audio_device_selected] Invalid selection: {e}")
        raise RuntimeError("Invalid audio device selection.")

    append_or_update_env(env_file_path, device_env_var, new_device)
    logger.info(f"[ensure_audio_device_selected] Selected device '{new_device}' stored in '{env_file_path}' under '{device_env_var}'.")

if __name__ == "__main__":
    try:
        ensure_audio_device_selected(
            env_file_path="./config/.env", 
            device_env_var="CHATZILLA_MIC_DEVICE_NAME"
        )
        logger.info("[main] Startup audio device setup complete.")
    except RuntimeError as e:
        logger.error(f"[main] Audio setup failed: {e}")
