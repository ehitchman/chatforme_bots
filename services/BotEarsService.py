import soundfile as sf
import sounddevice as sd
import numpy as np
import asyncio
import json
import os
from collections import deque

from my_modules import my_logging

runtime_logger_level = 'DEBUG'

class BotEars:
    def __init__(
        self,
        audio_filepath,
        device_name,
        buffer_length_seconds,
        hostapi_name="Windows WASAPI",
        samplerate=None
    ):
        """
        Initializes the BotEars class with audio capture settings.
        We will attempt to open the device with its max_input_channels,
        then fallback if that fails.

        Args:
            config: Configuration object containing paths and other settings.
            device_name (str): Name of the audio device to capture from.
            buffer_length_seconds (int): Duration of the audio buffer in seconds.
            hostapi_name (str): Name of the host API to use (default is Windows WASAPI).
            samplerate (int, optional): Desired sample rate. If not provided, the device default is used.
        """
        self.logger = my_logging.create_logger(
            debug_level=runtime_logger_level,
            logger_name="logger_BotEars",
            mode="w",
            stream_logs=True
        )

        botears_audio_dirpath = os.path.dirname(audio_filepath)
        botears_audio_filename = os.path.basename(audio_filepath)

        if not os.path.exists(botears_audio_dirpath):
            os.makedirs(botears_audio_dirpath)

        try:
            hostapis = sd.query_hostapis()
            hostapi_index = next(
            (index for index, api in enumerate(hostapis) if api["name"] == hostapi_name),
            None,
            )
        except Exception as e:
            raise RuntimeError(f"Error querying host APIs: {e}")
        if hostapi_index is None:
            raise ValueError(f"Host API '{hostapi_name}' not available.")

        try:
            device_index = self.find_device_index(device_name, hostapi_index)
        except ValueError as e:
            raise ValueError(f"Initialization error: {e}")

        # Get device details
        device_info = sd.query_devices()[device_index]
        self.logger.debug(f"Found device: {json.dumps(device_info, indent=4)}")

        if device_info["max_input_channels"] == 0:
            raise ValueError(f"Device '{device_name}' does not support input.")

        # Use the device's default sample rate if not provided
        self.samplerate = samplerate or int(device_info["default_samplerate"])
        self.logger.info(
            f"Device supports up to {device_info['max_input_channels']} channels. "
            f"Default sample rate: {self.samplerate} Hz"
        )

        # This is the channel count we *attempt* to open.
        self.stream_channels = device_info["max_input_channels"]
        self.logger.debug(f"Attempting to open stream with {self.stream_channels} channels.")

        self.stream = None
        fallback_channels = [1] #[device_info["max_input_channels"], 2, 1] (20250105 - doesn't seem to work using multiple channels)
        opened_ok = False
        last_error = None

        for ch in fallback_channels:
            try:
                self.logger.debug(f"Trying {ch} channel(s) for the InputStream.")
                self._try_open_stream(device_index, ch)
                self.logger.info(f"Successfully opened InputStream with {ch} channels.")
                self.stream_channels = ch
                opened_ok = True
                break
            except sd.PortAudioError as e:
                last_error = e
                self.logger.warning(f"Failed to open stream with {ch} channels. Error: {e}")

        if not opened_ok:
            raise RuntimeError(
                f"Could not open stream at all. Last error: {last_error}"
            )

        # Initialize the buffer based on how many *mono* samples we plan to keep.
        # We only store/consume data as mono, even if we open multiple channels.
        self.buffer = deque(
            maxlen=buffer_length_seconds * self.samplerate
        )

    def _try_open_stream(self, device_index, channels):
        """
        Attempt to open an InputStream with the specified number of channels.
        If it fails, raise an exception so we can fallback.
        """
        sd.Stream()
        wasapi_info = sd.WasapiSettings(exclusive=False)
        self.stream = sd.InputStream(
            device=device_index,
            samplerate=self.samplerate,
            channels=channels,
            callback=self._audio_callback,
            extra_settings=wasapi_info
        )
        # We won't call `start()` here; that happens below in start_botears_audio_stream

    def _audio_callback(self, indata, frames, time, status):
        """
        Audio callback function. We always downmix to mono by averaging across channels.
        """
        if status:
            self.logger.warning(f"Audio callback status: {status}")

        # Reduce the data to mono by averaging across channels
        mono_data = np.mean(indata, axis=1)  # shape: (frames,)
        self.buffer.extend(mono_data)

    def find_device_index(self, device_name, hostapi):
        """
        Find the index of a device by name and host API.

        Args:
            device_name (str): The name of the audio device.
            hostapi (int): The host API index to filter devices.

        Returns:
            int: The index of the matching device.

        Raises:
            ValueError: If no matching device is found.
        """
        devices = sd.query_devices()
        for index, device in enumerate(devices):
            if device["hostapi"] == hostapi and device_name in device["name"]:
                return index
        raise ValueError(f"Device '{device_name}' not found with host API {hostapi}.")

    async def start_botears_audio_stream(self):
        """
        Start the audio stream continuously.
        """
        if not self.stream:
            self.logger.error("Stream not created. Cannot start.")
            return

        try:
            self.stream.start()
            self.logger.info(
                f"Audio input stream started with {self.stream_channels} channels (downmixed to mono)."
            )
        except sd.PortAudioError as e:
            self.logger.error(f"Error starting audio stream: {e}")

    async def save_last_n_seconds(self, filepath, saved_seconds):
        """
        Save the last N seconds of MONO audio to a WAV file.
        """
        num_samples = saved_seconds * self.samplerate
        audio_data = np.array(self.buffer)

        # If we haven't captured enough audio yet, this might be shorter
        if len(audio_data) > num_samples:
            audio_data = audio_data[-num_samples:]

        sf.write(filepath, audio_data, self.samplerate, format="WAV")
        self.logger.info(f"Saved {len(audio_data)/self.samplerate:.2f} sec of mono audio to {filepath}")

    def save_audio_device_details(self, output_filepath):
        """
        Save details of all available audio devices to a JSON file.
        
        Args:
            output_filepath (str): The file path where device details will be saved.
        """
        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()

            # Collect device details with corresponding host APIs
            device_details = []
            for index, device in enumerate(devices):
                device_details.append({
                    "index": index,
                    "name": device["name"],
                    "hostapi": hostapis[device["hostapi"]]["name"],
                    "max_input_channels": device["max_input_channels"],
                    "max_output_channels": device["max_output_channels"],
                    "default_samplerate": device["default_samplerate"]
                })

            # Save to JSON file
            with open(output_filepath, "w", encoding="utf-8") as f:
                json.dump(device_details, f, indent=4)

            self.logger.info(f"Audio device details saved to {output_filepath}")
        except Exception as e:
            self.logger.error(f"Error saving audio device details: {e}")

if __name__ == "__main__":
    import asyncio

    async def run_test():
        from classes.ConfigManagerClass import ConfigManager

        os.environ['CHATZILLA_CONFIG_DIRPATH'] = r'C:\_repos\chatzilla_ai\config'
        os.environ['CHATZILLA_YAML_FILE'] = 'chatzilla_ai_ehitch.yaml'
        os.environ['CHATZILLA_ENV_FILENAME'] = '.env'
        os.environ['CHATZILLA_KEYS_ENV_DIRPATH'] = 'keys'
        os.environ['CHATZILLA_KEYS_ENV_FILENAME'] = '.env.keys'
        os.environ['CHATZILLA_YAML_PATH'] = r'.\config\bot_user_configs' '\\' + os.getenv('CHATZILLA_YAML_FILE')        
        print(f"yaml_filepath_type: {type(os.environ['CHATZILLA_YAML_PATH'])}")

        ConfigManager.initialize(yaml_filepath=os.environ['CHATZILLA_YAML_PATH'])
        config = ConfigManager.get_instance()

        device_name = "Microphone (Yeti Classic)"
        botears_audio_filepath = os.path.join(config.botears_audio_path, config.botears_audio_filename)

        try:
            ears = BotEars(
                audio_filepath=botears_audio_filepath,
                device_name=device_name,
                buffer_length_seconds=5
            )
        except Exception as e:
            print(f"Error creating BotEars instance: {e}")
            return

        await ears.start_botears_audio_stream()

        print("Recording for 5 seconds...")
        await asyncio.sleep(5)

        # Save the last 5 seconds
        audio_path = os.path.join(config.botears_audio_path, config.botears_audio_filename + ".wav")
        print(f"Saving the last 5 seconds of audio to: {audio_path}")
        await ears.save_last_n_seconds(
            filepath=audio_path, 
            saved_seconds=5
            )

        print("Done. Check your WAV file for playback!")

    asyncio.run(run_test())