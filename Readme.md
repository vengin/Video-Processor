# Video Compression Processor

A Python GUI application for video files batch processing, with compression and tempo (speed) change, to reduce file size. The application uses FFmpeg (and FFprobe) for video processing in multi-threading mode and supports multiple video formats.

![Video Compression Processor GUI](./docs/Video-Compression-Processor(GUI).png)

## Features

- Video compression
- Batch processing with multi-threading support
- Change video files tempo (with preserving the pitch)
- Supports multiple video formats (MP4, MKV, AVI, WEBM, FLV, WMV)
- Dynamic progress tracking for individual files and overall progress, based on processed time feedback from FFMPEG
- Configurable file overwrite behavior (Skip/Overwrite/Rename)
- Settings persistence between sessions (saves its configuration in a config file)
- File processsing Cancelation🔴 (left double-click) or Pausing🟡 / Resuming🟢 (right-click)

## Requirements

- Python 3.x
- FFmpeg and FFprobe executables
- Python packages:
  - tkinter (usually comes with Python)
  - configparser
  - psutil

## Installation

1. Ensure Python 3.x is installed on your system
2. Download and install FFmpeg (with FFprobe)
3. Download `video_processor.py` and run it

## Configuration

The application saves its configuration in `video_processor_config.ini`. This file is always resolved relative to the directory where the script is located.

The configuration includes:
- **FFmpeg path**: This must be an **absolute path** to the FFmpeg executable.
- Last used input (source) and output (destination) directories
- Tempo value
- Number of processing threads
- Overwrite options

## Usage

1. **Set FFmpeg path**: Provide the absolute path to your FFmpeg executable.
2. **Select Source/Destination Directories**:
   - Both **absolute** and **relative paths** are supported for source and destination directories.
   - Relative paths are resolved starting from the directory where the script itself is located.
3. Adjust tempo value (0.1-2.0, where 1.0 is normal speed)
4. Choose number of processing threads (1-DFLT_N_THREADS_MAX)
5. Select file overwrite behavior:
   - Skip existing files
   - Overwrite existing files
   - Rename existing files
6. Select Encoding Preset (Slow, Fast, or Custom)
7. Click "Run" to start processing

## Interaction

- **Pause/Resume**: Right-click on a file progress bar in processing list to Pause🟡 or Resume🟢 its processing.
- **Cancel**: Double-click on a file progress bar in processing list to Cancel🔴 its processing.

| File Processing Status      | Progress Bar Color      |
| ------------- | ------------- |
| Normal processing; Resumed; next after Canceled | 🟢 Green |
| Paused (right-click); or when "Cancel Processing?" message box is shown after a left double-click | 🟡 Yellow |
| Canceled (and there are no next files to schedule) | 🔴 Red |

## Processing Options

- **Encoding Presets**:
  - **Preset1: Slow**: High efficiency AV1 encoding (`libaom-av1`, CRF 30) configured for smaller file sizes.
  - **Preset2: Fast**: Faster H.264 encoding (`libx264`, fast preset, CRF 25) configured for speed.
  - **Preset3: Custom**: Fully customizable H.264 encoding where you can change core FFMPEG options (more details in [Preset3: Custom](#preset3-custom)).
- **Tempo**: Value between 0.1 and 2.0
  - < 1.0: Slower playback
  - 1.0: Normal speed
  - \> 1.0: Faster playback
- **Threads**: 1-DFLT_N_THREADS_MAX concurrent processing threads
- **Overwrite Options**:
  - Skip: Preserve existing files
  - Overwrite: Replace existing files
  - Rename: Add number suffix to new files

## FFMPEG parameters

The FFMPEG command used for **Preset1: Slow compression (without tempo)** is the following:

```
# Cmd example:
# ffmpeg.exe -i i.mp4 -filter:v setpts=0.66666667*PTS,scale=640:360 -filter:a atempo=1.5 -vf scale=640:360 -pix_fmt yuv420p -c:v libaom-av1 -b:v 70k -crf 30 -cpu-used 8 -row-mt 1 -g 240 -aq-mode 0 -c:a aac -b:a 80k o.mp4 -y -progress pipe:1 -nostats -hide_banner -loglevel error
ffmpeg_command = [
  str(self.ffmpeg_path.get()),
  # General options
  "-i", src_file_path,            # Input file
  # Filter options
  "-vf", "scale=640:360",         # Video filter for scaling
  "-pix_fmt", "yuv420p",          # Pixel format for compatibility
  # Video options
  "-c:v", "libaom-av1",           # Video codec: AV1
  "-b:v", "70k",                  # Video bitrate
  "-crf", "30",                   # Constant Rate Factor (quality)
  "-row-mt", "1",                 # Enable row-based multithreading
  "-g", "240",                    # Group of pictures (GOP) size
  "-aq-mode", "0",                # Adaptive quantization mode
  # Audio options
  "-c:a", "aac",                  # Audio codec: AAC
  "-b:a", "80k",                  # Audio bitrate
  # Output options
  dst_file_path,
  "-y",                           # Force overwrite output file
  # Progress reporting
  "-progress", "pipe:1",          # Pipe progress to stdout
  "-nostats",                     # Disable default stats output
  # Logging options
  "-hide_banner",                 # Hide FFmpeg banner
  "-loglevel", "error",           # Set log level to error
]
```

When **Tempo** is used (Tempo != 1), additional parameters are added:

```
# If tempo is not 1, we need to adjust both video and audio streams
# For video files we need to use tempo value for audio stream and PTS=1/tempo for video
PTS = 1 / self.tempo.get() # PTS is 1/tempo
ffmpeg_tempo_params = [
  "-filter:v", f"setpts={PTS:.8f}*PTS,scale=640:360", # Video filter for changing speed and scaling
  "-filter:a", f"atempo={self.tempo.get()}",          # Audio filter for changing tempo
]
# Replace ["-vf", "scale=640:360"], use single combined video filter
# Cmd example:
# ffmpeg.exe -i i.mp4 -filter:v setpts=0.66666667*PTS,scale=640:360 -filter:a atempo=1.5 -vf scale=640:360 -pix_fmt yuv420p -c:v libaom-av1 -b:v 70k -crf 30 -cpu-used 8 -row-mt 1 -g 240 -aq-mode 0 -c:a aac -b:a 80k o.mp4 -y -progress pipe:1 -nostats -hide_banner -loglevel error
ffmpeg_command[3:5] = ffmpeg_tempo_params
```

## Logging

The application logs processing details and errors to `video_processor.log` file ('INFO' or 'DEBUG' modes).

## Preset3: Custom

**Preset3: Custom**: Fully customizable H.264 encoding where you can chose the core FFMPEG options:
- **-preset** option: from `ultrafast` to `placebo`
- **-tune** option (optional): `film`, `animation`, `grain`, `stillimage`, `psnr`, `ssim`, `fastdecode`, `zerolatency`
- **Constant Rate Factor (CRF)**: range 10-51
- **Fixed Height**: Set `fixed height` for output video, automatically calculating `VF Scale` parameter for each video (GUI `Video Filter (VF) Scale` is ignored)
- **Video Filter (VF) Scale**: range 0.25-1.0
- **Audio Bitrate (-b:a)**: e.g. 64k, 96K, 1M
![Video Compression Processor - Preset3: Custom](./docs/Video-Compression-Processor_Preset3-Custom(GUI).png)
