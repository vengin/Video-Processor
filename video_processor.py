import tkinter as tk
from tkinter import filedialog
from tkinter import ttk
from tkinter import scrolledtext
from tkinter import messagebox
from datetime import datetime
import json
import configparser
import os
import subprocess
import threading
import queue
import time
import logging
import psutil

# Default values for the application
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DFLT_FFMPEG_PATH = "d:/PF/_Tools/ffmpeg/bin/ffmpeg.exe"  # Change this if your ffmpeg path is different.
DFLT_SRC_DIR = ""
DFLT_DST_DIR = ""
DFLT_TEMPO = 1.0
DFLT_N_THREADS = 4
DFLT_N_THREADS_MAX = 16
DFLT_CONFIG_FILE = os.path.join(SCRIPT_DIR, "video_processor_config.ini")
DFLT_LOG_FILE = os.path.join(SCRIPT_DIR, "video_processor.log")
VID_EXT = ('.mp4', '.mkv', 'avi', '.webm', '.flv', '.wmv')
DFLT_OVERWRITE_OPTION = "Skip existing files"  # Skip by default
DFLT_PRESET = "Preset1: Slow"
DFLT_CRF = 23
DFLT_VF_SCALE = 0.5
DFLT_AUDIO_BITRATE = "64k"
DFLT_CUSTOM_PRESET = "fast"
DFLT_TUNE_ENABLED = False
DFLT_CUSTOM_TUNE = "film"
DFLT_PRESERVE_TIMESTAMPS = True

# MIN/MAX values for custom parameters
MIN_CRF = 10
MAX_CRF = 51
MIN_VF_SCALE = 0.25
MAX_VF_SCALE = 1.0
MIN_TEMPO = 0.1
MAX_TEMPO = 2.0
GUI_TIMEOUT = 0.3 # in seconds
UPDATE_STATUS_TIMEOUT = 1 # in seconds
THREAD_PROGRESS_TIMEOUT = 300  # seconds (0 to disable)


#############################################################################
class CustomProgressBar(tk.Canvas):
  """
  Custom progress bar class for displaying processing progress.
  Inherits from tkinter Canvas widget.
  """
  def __init__(self, master, use_bold_font=False, *args, **kwargs):
    super().__init__(master, *args, **kwargs)
    self.progress_var = tk.DoubleVar()
    self.filename_var = tk.StringVar()
    self.paused = tk.BooleanVar(value=False)
    self.cancelled = tk.BooleanVar(value=False)
    self.relative_path = None

    # Set bald font based on parameter
    self.text_font = ('TkDefaultFont', 9, 'bold') if use_bold_font else ('TkDefaultFont', 9)

    # Bind configure event to handle resizing
    self.bind("<Configure>", self.draw_progress_bar)

    # Initial draw
    self.draw_progress_bar()


  #############################################################################
  def draw_progress_bar(self, event=None):
    """Redraws the progress bar based on current progress and filename."""
    self.delete("all")  # Clear canvas

    # Get current dimensions
    width = self.winfo_width()
    height = self.winfo_height()

    # Calculate progress width
    progress = self.progress_var.get()
    fill_width = int((width - 5) * (progress / 100))  # Adjusted for border

    # Draw border rectangle first
#    self.create_rectangle(2, 2, width-2, height-2,  outline="black", width=1)
    self.create_rectangle(2, 2, width-2, height-2,  outline="black")

    # Draw progress fill inside the border
    if fill_width > 0:
      fill_color = "#A8D8A8"  # Default green
      if self.paused.get():
        fill_color = "#F8EA90"  # Yellow for paused
      if self.cancelled.get():
        fill_color = "#FF9999"  # Red for cancelled
      self.create_rectangle(2, 2, fill_width + 2, height - 2, fill=fill_color)

    # Draw centered text
    self.create_text(
      width / 2, height / 2,
      text=self.filename_var.get(),
      anchor="center",
      fill="black",
      font=self.text_font  # Bald font (optionally)
    )


  #############################################################################
  def set_progress(self, value):
    """Sets the progress value and redraws the bar."""
    self.progress_var.set(value)
    self.draw_progress_bar()


  #############################################################################
  def set_display_text(self, display_text):
    """Sets the display text (filename) and redraws the bar."""
    self.filename_var.set(display_text)
    self.draw_progress_bar()


  #############################################################################
  def prepare_new_file(self, display_text):
    """Prepares the progress bar for a new file by resetting its state."""
    self.filename_var.set(display_text)
    self.progress_var.set(0)
    self.paused.set(False)
    self.cancelled.set(False)
    self.draw_progress_bar()


#############################################################################
class VideoProcessor:
  """
  Main class for the Video Compression Processor application.
  Handles GUI interaction, configuration, and processing logic.
  """
  def __init__(self, master):
    self.master = master
    master.title("Video Compression Processor")

    # Pre-define elements\variables (to avoid linter warnings and errors)
    self.run_button = None
    self.overwrite_options = tk.StringVar(value=DFLT_OVERWRITE_OPTION)
    self.preset = tk.StringVar(value=DFLT_PRESET)
    self.crf = tk.StringVar(value=str(DFLT_CRF))
    self.vf_scale = tk.StringVar(value=str(DFLT_VF_SCALE))
    self.audio_bitrate = tk.StringVar(value=DFLT_AUDIO_BITRATE)
    self.custom_preset = tk.StringVar(value=DFLT_CUSTOM_PRESET)
    self.tune_enabled = tk.BooleanVar(value=DFLT_TUNE_ENABLED)
    self.custom_tune = tk.StringVar(value=DFLT_CUSTOM_TUNE)
    self.preserve_timestamps = tk.BooleanVar(value=DFLT_PRESERVE_TIMESTAMPS)

    # Initialize GUI variables as empty
    self.ffmpeg_path = tk.StringVar()
    self.tempo = tk.DoubleVar()
    self.src_dir = tk.StringVar()
    self.dst_dir = tk.StringVar()
    self.n_threads = tk.IntVar()

    # Load application configuration
    self.config = configparser.ConfigParser()
    self.load_config()

    # Init variables
    self.progress_bars = []
    self.progress_bars_idx = []
    self.active_threads = 0
    self.total_files = 0
    self.processed_files = 0
    self.processed_files_lock = threading.Lock()  # Lock for thread-safe access
    self.processed_seconds_arr = {}
    self.processed_seconds_arr_lock = threading.Lock()  # Lock for thread-safe access
    self.total_dst_seconds = 0  # Total size of all files
    self.total_dst_seconds_lock = threading.Lock()  # Lock for thread-safe access
    self.total_dst_sz = 0
    self.total_src_sz = 0
    self.error_files = 0
    self.skipped_files = 0
    self.cancelled_files = 0
    self.status_text = None
    self.start_time = None
    self.processing_complete = False
    self.processed_files_set = set()
    self.processed_dst_files_set = set()  # Track actual destination file paths
    self.processing_complete_event = threading.Event()
    self.active_processes = {}  # Change to a dictionary {pid: process_object}
    self.processes_lock = threading.Lock()  # Add lock for thread-safe access
    self.progress_bar_to_pid = {}  # Maps progress bar to process pid

    # Create GUI elements
    self.create_widgets()
    # Initialize threading components
    self.queue = queue.Queue()
    self.gui_queue = queue.Queue()  # Queue for GUI updates
    self.threads = []

    # Bind the save_config method to the window close event.
    self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    self.setup_logging('INFO')  # 'INFO' or 'DEBUG' for more detailed logging
    logging.info("VideoProcessor initialized")

    self.status_update_queue = queue.Queue()
    self.status_update_thread = threading.Thread(target=self.process_status_updates, daemon=True) # Explicitly set daemon
    self.status_update_thread.start()
    logging.info("Status update thread started.")

    # Using this flag for more gracefull shutdown, if closing application while files are still processed
    self.is_shutting_down = False


  def resolve_path(self, path_str):
    """Resolves relative paths against the script's directory."""
    if not path_str:
      return ""
    if os.path.isabs(path_str):
      return os.path.normpath(path_str)
    return os.path.normpath(os.path.join(SCRIPT_DIR, path_str))


  #############################################################################
  def load_config(self):
    """Loads config from video_processor_config.ini or uses defaults if not found."""
    if not self.config.read(DFLT_CONFIG_FILE):
      logging.warning("Config file not found. Using defaults.")
      self.config['DEFAULT'] = {
        'ffmpeg_path': DFLT_FFMPEG_PATH,
        'tempo': str(DFLT_TEMPO),
        'src_dir': DFLT_SRC_DIR,
        'dst_dir': DFLT_DST_DIR,
        'n_threads': str(DFLT_N_THREADS),
        'overwrite_option': DFLT_OVERWRITE_OPTION,  # Skip by default
        'preserve_timestamps': str(DFLT_PRESERVE_TIMESTAMPS),
      }
    else:
      try:
        # Set the values using the loaded configuration or defaults
        self.ffmpeg_path.set(self.config['DEFAULT'].get('ffmpeg_path', DFLT_FFMPEG_PATH))
        self.src_dir.set(self.config['DEFAULT'].get('src_dir', DFLT_SRC_DIR))
        self.dst_dir.set(self.config['DEFAULT'].get('dst_dir', DFLT_DST_DIR))
        self.overwrite_options.set(self.config['DEFAULT'].get('overwrite_option', DFLT_OVERWRITE_OPTION))
        self.preset.set(self.config['DEFAULT'].get('preset', DFLT_PRESET))

        try:
          tempo_val = float(self.config['DEFAULT'].get('tempo', str(DFLT_TEMPO)))
          if tempo_val <= MIN_TEMPO or tempo_val > MAX_TEMPO:
            tempo_val = DFLT_TEMPO
        except ValueError:
          tempo_val = DFLT_TEMPO
        self.tempo.set(tempo_val)

        try:
          n_threads_val = int(self.config['DEFAULT'].get('n_threads', str(DFLT_N_THREADS)))
          if n_threads_val < 1 or n_threads_val > DFLT_N_THREADS_MAX:
             n_threads_val = DFLT_N_THREADS
        except ValueError:
          n_threads_val = DFLT_N_THREADS
        self.n_threads.set(n_threads_val)

        try:
          crf_val = int(self.config['DEFAULT'].get('crf', str(DFLT_CRF)))
          if crf_val < MIN_CRF or crf_val > MAX_CRF:
            crf_val = DFLT_CRF
        except ValueError:
          crf_val = DFLT_CRF
        self.crf.set(str(crf_val))

        try:
          vf_scale_val = float(self.config['DEFAULT'].get('vf_scale', str(DFLT_VF_SCALE)))
          if vf_scale_val < MIN_VF_SCALE or vf_scale_val > MAX_VF_SCALE:
            vf_scale_val = DFLT_VF_SCALE
        except ValueError:
          vf_scale_val = DFLT_VF_SCALE
        self.vf_scale.set(str(vf_scale_val))

        import re
        ab_val = self.config['DEFAULT'].get('audio_bitrate', DFLT_AUDIO_BITRATE)
        if not ab_val or not re.match(r'^\d+[kKmM]$', ab_val):
          ab_val = DFLT_AUDIO_BITRATE
        self.audio_bitrate.set(ab_val)

        cp_val = self.config['DEFAULT'].get('custom_preset', DFLT_CUSTOM_PRESET)
        valid_presets = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow", "placebo"]
        if cp_val not in valid_presets:
          cp_val = DFLT_CUSTOM_PRESET
        self.custom_preset.set(cp_val)

        tune_en_val = self.config['DEFAULT'].getboolean('tune_enabled', DFLT_TUNE_ENABLED)
        self.tune_enabled.set(tune_en_val)

        ct_val = self.config['DEFAULT'].get('custom_tune', DFLT_CUSTOM_TUNE)
        valid_tunes = ["film", "animation", "grain", "stillimage", "psnr", "ssim", "fastdecode", "zerolatency"]
        if ct_val not in valid_tunes:
          ct_val = DFLT_CUSTOM_TUNE
        self.custom_tune.set(ct_val)

        pt_val = self.config['DEFAULT'].getboolean('preserve_timestamps', DFLT_PRESERVE_TIMESTAMPS)
        self.preserve_timestamps.set(pt_val)
      except Exception as e:
        messagebox.showerror("Config Error", f"Could not load config file: {e}")


  #############################################################################
  def save_config(self):
    """Saves application configuration to video_processor_config.ini."""
    if self.validate_tempo():
      self.config['DEFAULT']['tempo'] = str(self.tempo.get())
    else:
      self.config['DEFAULT']['tempo'] = str(DFLT_TEMPO)

    self.config['DEFAULT']['n_threads'] = str(self.n_threads.get())
    self.config['DEFAULT']['ffmpeg_path'] = self.ffmpeg_path.get()
    self.config['DEFAULT']['src_dir'] = self.src_dir.get()
    self.config['DEFAULT']['dst_dir'] = self.dst_dir.get()
    self.config['DEFAULT']['overwrite_option'] = self.overwrite_options.get()
    self.config['DEFAULT']['preset'] = self.preset.get()
    self.config['DEFAULT']['crf'] = self.crf.get()
    self.config['DEFAULT']['vf_scale'] = self.vf_scale.get()
    self.config['DEFAULT']['audio_bitrate'] = self.audio_bitrate.get()
    self.config['DEFAULT']['custom_preset'] = self.custom_preset.get()
    self.config['DEFAULT']['tune_enabled'] = str(self.tune_enabled.get())
    self.config['DEFAULT']['custom_tune'] = self.custom_tune.get()
    self.config['DEFAULT']['preserve_timestamps'] = str(self.preserve_timestamps.get())
    try:
      with open(DFLT_CONFIG_FILE, 'w') as configfile:
        self.config.write(configfile)
    except Exception as e:
      messagebox.showerror("Config Error", f"Could not save config file: {e}")


  #############################################################################
  def create_widgets(self):
    """Creates and arranges GUI elements."""
    # Tempo
    ttk.Label(self.master, text="Tempo:").grid(row=0, column=0, sticky=tk.W, padx=5)
    tempo_entry = ttk.Entry(self.master, textvariable=self.tempo, width=5)
    tempo_entry.grid(row=0, column=1, sticky=tk.W)
    tempo_entry.bind('<FocusOut>', self.on_tempo_focusout)

    # Source Directory Path
    ttk.Button(self.master, text="SrcDir", command=self.browse_src_dir).grid(row=1, column=0)
    ttk.Entry(self.master, textvariable=self.src_dir, width=200).grid(row=1, column=1, sticky=tk.W)

    # Destination Directory Path
    ttk.Button(self.master, text="DstDir", command=self.browse_dst_dir).grid(row=2, column=0)
    ttk.Entry(self.master, textvariable=self.dst_dir, width=200).grid(row=2, column=1, sticky=tk.W)

    # Number of threads 1-DFLT_N_THREADS_MAX
    ttk.Label(self.master, text="Number of threads:").grid(row=3, column=0, sticky=tk.W, padx=5)
    threads_frame = ttk.Frame(self.master)
    threads_frame.grid(row=3, column=1, sticky=tk.W)

    n_thread_values = list(range(1, DFLT_N_THREADS_MAX+1))  # Creates a list from 1 to DFLT_N_THREADS_MAX
    self.n_threads_combo = ttk.Combobox(threads_frame, textvariable=self.n_threads, values=n_thread_values, width=3, state="readonly")
    self.n_threads_combo.pack(side=tk.LEFT)

    # File options in row 4
    ttk.Label(self.master, text="File Overwrite Options:").grid(row=4, column=0, sticky=tk.W, padx=5)
    file_opts_frame = ttk.Frame(self.master)
    file_opts_frame.grid(row=4, column=1, sticky=tk.W)

    self.overwrite_options_combobox = ttk.Combobox(file_opts_frame,
      textvariable=self.overwrite_options,
      values=[ "Skip existing files", "Overwrite existing files", "Rename existing files"],
      state="readonly")
    self.overwrite_options_combobox.pack(side=tk.LEFT)

    self.preserve_timestamps_cb = ttk.Checkbutton(file_opts_frame, text="Preserve Original Modification Time", variable=self.preserve_timestamps)
    self.preserve_timestamps_cb.pack(side=tk.LEFT, padx=(20, 0))

    # Preset choice
    ttk.Label(self.master, text="Encoding Preset:").grid(row=5, column=0, sticky=tk.W, padx=5)
    preset_frame = ttk.Frame(self.master)
    preset_frame.grid(row=5, column=1, sticky=tk.W)

    self.preset_combobox = ttk.Combobox(preset_frame,
      textvariable=self.preset,
      values=["Preset1: Slow", "Preset2: Fast", "Preset3: Custom"],
      state="readonly", width=15)
    self.preset_combobox.pack(side=tk.LEFT)
    self.preset_combobox.bind("<<ComboboxSelected>>", self.on_preset_change)

    self.custom_opts_frame = ttk.Frame(preset_frame)
    self.custom_opts_frame.pack(side=tk.LEFT, padx=(10, 0))

    ttk.Label(self.custom_opts_frame, text="FFMPEG Preset:").pack(side=tk.LEFT, padx=(0, 2))
    self.custom_preset_combobox = ttk.Combobox(self.custom_opts_frame,
      textvariable=self.custom_preset,
      values=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow", "placebo"],
      state="readonly", width=9)
    self.custom_preset_combobox.pack(side=tk.LEFT, padx=(0, 10))

    self.tune_checkbox = ttk.Checkbutton(self.custom_opts_frame, text="-tune", variable=self.tune_enabled, command=self.on_tune_toggle)
    self.tune_checkbox.pack(side=tk.LEFT, padx=(0, 2))

    self.custom_tune_combobox = ttk.Combobox(self.custom_opts_frame,
      textvariable=self.custom_tune,
      values=["film", "animation", "grain", "stillimage", "psnr", "ssim", "fastdecode", "zerolatency"],
      state="readonly", width=11)
    self.custom_tune_combobox.pack(side=tk.LEFT, padx=(0, 10))
    self.on_tune_toggle()

    ttk.Label(self.custom_opts_frame, text="Constant Rate Factor (CRF):").pack(side=tk.LEFT, padx=(0, 2))
    self.crf_entry = ttk.Entry(self.custom_opts_frame, textvariable=self.crf, width=4)
    self.crf_entry.pack(side=tk.LEFT, padx=(0, 10))
    self.crf_entry.bind('<FocusOut>', self.on_crf_focusout)

    ttk.Label(self.custom_opts_frame, text="VF Scale:").pack(side=tk.LEFT, padx=(0, 2))
    self.vf_scale_entry = ttk.Entry(self.custom_opts_frame, textvariable=self.vf_scale, width=4)
    self.vf_scale_entry.pack(side=tk.LEFT, padx=(0, 10))
    self.vf_scale_entry.bind('<FocusOut>', self.on_vf_scale_focusout)

    ttk.Label(self.custom_opts_frame, text="Audio Bitrate:").pack(side=tk.LEFT, padx=(0, 2))
    self.audio_bitrate_entry = ttk.Entry(self.custom_opts_frame, textvariable=self.audio_bitrate, width=5)
    self.audio_bitrate_entry.pack(side=tk.LEFT)
    self.audio_bitrate_entry.bind('<FocusOut>', self.on_audio_bitrate_focusout)

    self.on_preset_change()  # initialize state

    # Run button
    self.run_button = tk.Button(self.master, text="Run", command=self.start_processing, state=tk.NORMAL, height=2, width=20)
    self.run_button.grid(row=6, column=1, pady=10)  # Added pady for vertical space

    # Create a frame to hold the status_text and scrollbar
    status_frame = ttk.Frame(self.master)
    status_frame.grid(row=7, column=0, columnspan=2, sticky='nsew', padx=5, pady=5)

    # Create the status_text widget
    self.status_text = tk.Text(status_frame, height=10, width=165, wrap=tk.WORD, state=tk.DISABLED)
    self.status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # Create the scrollbar
    scrollbar = ttk.Scrollbar(status_frame, orient=tk.VERTICAL, command=self.status_text.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # Configure the status_text to use the scrollbar
    self.status_text.config(yscrollcommand=scrollbar.set)


  #############################################################################
  def browse_src_dir(self):
    """Opens a directory selection dialog for the source directory."""
    directory = filedialog.askdirectory(initialdir=self.resolve_path(self.src_dir.get()))
    if directory:  # Check if a directory was selected
      self.src_dir.set(os.path.normpath(directory))


  #############################################################################
  def browse_dst_dir(self):
    """Opens a directory selection dialog for the destination directory."""
    directory = filedialog.askdirectory(initialdir=self.resolve_path(self.dst_dir.get()))
    if directory:  # Check if a directory was selected
      self.dst_dir.set(os.path.normpath(directory))


  #############################################################################
  def on_preset_change(self, event=None):
    """Shows or hides custom options based on preset selection."""
    if self.preset.get() == "Preset3: Custom":
      self.custom_opts_frame.pack(side=tk.LEFT, padx=(10, 0))
    else:
      self.custom_opts_frame.pack_forget()


  #############################################################################
  def on_tune_toggle(self, event=None):
    """Enables or disables custom tune options based on checkbox."""
    if self.tune_enabled.get():
      self.custom_tune_combobox.config(state="readonly")
    else:
      self.custom_tune_combobox.config(state="disabled")


  #############################################################################
  def check_executables(self):
    """Verifies that FFMPEG and FFPROBE executables exist."""
    ffmpeg_path = self.ffmpeg_path.get()
    if not os.path.exists(ffmpeg_path):
      return False, f"FFMPEG not found at: {ffmpeg_path}\nPlease check and update the path in the config file."

    ffprobe_path = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe")
    if not os.path.exists(ffprobe_path):
      return False, f"FFPROBE not found at: {ffprobe_path}\nIt should be in the same folder as ffmpeg.exe."

    return True, ""


  #############################################################################
  def get_metadata_info(self, ffmpeg_path, src_file_path):
    """Gets media file metadata (Duration) using FFPROBE."""
    try:
      # Derive ffprobe_path from ffmpeg_path
      ffprobe_path = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe")
      if not os.path.exists(ffprobe_path):
        logging.error(f"FFPROBE not found at: {ffprobe_path}")
        return None, False

      ffprobe_cmd = [
        ffprobe_path, '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'json',
        src_file_path
      ]
      rslt = subprocess.run(ffprobe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
      info = json.loads(rslt.stdout)
      total_seconds = int(float(info['format']['duration']))  # seconds

    except subprocess.CalledProcessError as e:
      logging.error(f"FFPROBE error for {src_file_path}: {e.stderr}")
      return None, False
    except Exception as e:
      logging.error(f"Error getting Tag info from {src_file_path}: {e}")
      return None, False

    return total_seconds, True


  #############################################################################
  def handle_overwrite(self, dst_file_path, relative_path):
    """Handles overwrite logic based on user selection."""
    msg = ""
    overwrite_option = self.overwrite_options.get()
    dst_relative_path_base, ext = os.path.splitext(relative_path)
    dst_relative_path = dst_relative_path_base + ext
    resolved_dst_dir = self.resolve_path(self.dst_dir.get())
    dst_file_path = os.path.join(resolved_dst_dir, dst_relative_path)
    if os.path.exists(dst_file_path):
      if overwrite_option == "Overwrite existing files":  # Overwrite existing
        msg = f"Overwriting: {relative_path}"
        self.status_update_queue.put(msg)  # Use queue for status updates
        logging.debug(msg)
        return dst_file_path
      elif overwrite_option == "Rename existing files":  # Rename instead of overwriting
        base, ext = os.path.splitext(relative_path)
        i = 1
        while os.path.exists(os.path.join(resolved_dst_dir, f"{base}({i}){ext}")):
          i += 1
        dst_file_path = os.path.join(resolved_dst_dir, f"{base}({i}){ext}")
        msg = f"Renaming: {relative_path} to {os.path.basename(dst_file_path)}"
        self.status_update_queue.put(msg)  # Use queue for status updates
        logging.debug(msg)
        return dst_file_path
      elif overwrite_option == "Skip existing files":  # Skip processing
        msg = f"Skipping: {relative_path}"
        self.status_update_queue.put(msg)  # Use queue for status updates
        logging.debug(msg)
        return None  # Skip processing this file
    else:  # Normal output (no overwrite)
      msg = f"Processing: {relative_path}"
      self.status_update_queue.put(msg)  # Use queue for status updates
      logging.debug(msg)
      return dst_file_path


  #############################################################################
  def generate_ffmpeg_command(self, src_file_path, dst_file_path):
    """Generates FFMPEG command for compression with optional tempo."""
    # Convert paths to string and handle potential encoding issues
    src_file_path = str(src_file_path)
    base, ext = os.path.splitext(str(dst_file_path))
    dst_file_path = base + ext
    ext_lower = ext.lower()

    # Choose audio codec based on output container
    # WebM requires Vorbis or Opus audio; use Opus by default
    audio_codec = "libopus" if ext_lower == ".webm" else "aac"

    preset_choice = self.preset.get()

    if preset_choice == "Preset3: Custom":
      try:
        crf_val = str(min(max(int(self.crf.get()), MIN_CRF), MAX_CRF))
      except ValueError:
        crf_val = DFLT_CRF
        self.crf.set(crf_val)

      try:
        vf_scale_val = min(max(float(self.vf_scale.get()), MIN_VF_SCALE), MAX_VF_SCALE)
      except ValueError:
        vf_scale_val = DFLT_VF_SCALE
        self.vf_scale.set(str(vf_scale_val))

      audio_br = self.audio_bitrate.get()
      if not audio_br:
        audio_br = DFLT_AUDIO_BITRATE
        self.audio_bitrate.set(audio_br)

      custom_preset_val = self.custom_preset.get()
      if not custom_preset_val:
        custom_preset_val = DFLT_CUSTOM_PRESET
        self.custom_preset.set(custom_preset_val)

      custom_tune_val = self.custom_tune.get()
      if not custom_tune_val:
        custom_tune_val = DFLT_CUSTOM_TUNE
        self.custom_tune.set(custom_tune_val)

      ffmpeg_command = [
        str(self.ffmpeg_path.get()),
        # General options
        "-i", src_file_path,
        # Filter options
        "-vf", f"scale=iw*{vf_scale_val}:-2",
        "-pix_fmt", "yuv420p",
        "-preset", custom_preset_val,
        # Video options
        "-map", "0:v",
        "-c:v", "libx264",
        "-crf", crf_val,
#        "-cpu-used", "8",
        # Audio options
        "-map", "0:a",
        "-c:a", audio_codec,
        "-b:a", audio_br,
        "-ac", "2",
        "-af", "aresample=matrix_encoding=dplii",
        # Subtitles
        "-map", "0:s?",
        "-c:s", "copy",
        # Output options
        dst_file_path,
        "-y",  # Force overwrite output file
        # Progress reporting
        "-progress", "pipe:1",
        "-nostats",
        # Logging options
        "-hide_banner",
        "-loglevel", "error",
      ]

      if self.tune_enabled.get():
        idx = ffmpeg_command.index("-c:v")
        ffmpeg_command.insert(idx, "-tune")
        ffmpeg_command.insert(idx + 1, custom_tune_val)

    elif preset_choice == "Preset2: Fast":
      ffmpeg_command = [
        str(self.ffmpeg_path.get()),
        # General options
        "-i", src_file_path,
        # Filter options
        "-vf", "scale=iw*0.5:-2",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        # Video options
        "-map", "0:v",
        "-c:v", "libx264",
        "-tune", "film",
        "-crf", "25",
#        "-cpu-used", "8",
        # Audio options
        "-map", "0:a",
        "-c:a", audio_codec,
        "-b:a", "64k",
        # Subtitles
        "-map", "0:s?",
        "-c:s", "copy",
        # Output options
        dst_file_path,
        "-y",  # Force overwrite output file
        # Progress reporting
        "-progress", "pipe:1",
        "-nostats",
        # Logging options
        "-hide_banner",
        "-loglevel", "error",
      ]
    else:
      # Default to Preset1: Slow
      ffmpeg_command = [
        str(self.ffmpeg_path.get()),
        # General options
        "-i", src_file_path,
        # Filter options
        "-vf", "scale=640:360",
        "-pix_fmt", "yuv420p",
        # Video options
        "-map", "0:v",
        "-c:v", "libaom-av1",
        "-b:v", "70k",
        "-crf", "30",
#        "-cpu-used", "8",
        "-row-mt", "1",
        "-g", "240",
        "-aq-mode", "0",
        # Audio options
        "-map", "0:a",
        "-c:a", audio_codec,
        "-b:a", "80k",
        # Subtitles
        "-map", "0:s?",
        "-c:s", "copy",
        # Output options
        dst_file_path,
        "-y",  # Force overwrite output file
        # Progress reporting
        "-progress", "pipe:1", # Pipe progress to stdout
        "-nostats", # Disable default stats output
        # Logging options
        "-hide_banner",
        "-loglevel", "error",
      ]

    if self.tempo.get() != 1.0:
      # If tempo is not 1, we need to adjust both video and audio streams
      # For video files we need to use tempo value for audio stream and PTS=1/tempo for video
      PTS = 1 / self.tempo.get() # PTS is 1/tempo
      current_scale = ffmpeg_command[4]
      ffmpeg_tempo_params = [
        "-filter:v", f"setpts={PTS:.8f}*PTS,{current_scale}",
        "-filter:a", f"atempo={self.tempo.get()}",  # tempo audio filter
      ]
      # Replace ["-vf", current_scale], use single combined video filter
      # Cmd example:
      # ffmpeg.exe -i i.mp4 -filter:v setpts=0.66666667*PTS,scale=640:360 -filter:a atempo=1.5 -vf scale=640:360 -pix_fmt yuv420p -c:v libaom-av1 -b:v 70k -crf 30 -cpu-used 8 -row-mt 1 -g 240 -aq-mode 0 -c:a aac -b:a 80k o.mp4 -y -progress pipe:1 -nostats -hide_banner -loglevel error
      ffmpeg_command[3:5] = ffmpeg_tempo_params


    logging.info(f"Process File: FFMPEG command: {' '.join(ffmpeg_command)}")
    return ffmpeg_command


  #############################################################################
  def monitor_progress(self, process, progress_bar, dst_time, relative_path):
    """Monitors FFMPEG progress by reading stdout and updates the progress bar."""
    q = queue.Queue()

    def read_stdout(p, q):
      try:
        while True:
          line = p.stdout.readline()
          if not line:
            break
          q.put(('stdout', line.decode('utf-8', errors='replace')))
      finally:
        q.put(('stdout', None))

    def read_stderr(p, q):
      try:
        while True:
          line = p.stderr.readline()
          if not line:
            break
          q.put(('stderr', line.decode('utf-8', errors='replace')))
      finally:
        q.put(('stderr', None))

    stdout_thread = threading.Thread(target=read_stdout, args=(process, q))
    stdout_thread.daemon = True
    stdout_thread.start()

    stderr_thread = threading.Thread(target=read_stderr, args=(process, q))
    stderr_thread.daemon = True
    stderr_thread.start()

    last_change_time = time.time()
    last_processed_us = -1
    stdout_done = False
    stderr_done = False

    try:
      while True:
        try:
          stream, line = q.get(timeout=GUI_TIMEOUT)

          if line is None:
            if stream == 'stdout': stdout_done = True
            if stream == 'stderr': stderr_done = True
            if stdout_done and stderr_done:
              break
            continue

          # Any activity from FFmpeg (stdout or stderr) resets the timeout clock
          last_change_time = time.time()

          if stream == 'stderr':
            err_msg = line.strip()
            if err_msg:
              logging.error(f"FFMPEG StdErr [{relative_path}]: {err_msg}")
            continue

          # Process stdout progress lines
          if "out_time_ms=" in line or "out_time_us=" in line:
            parts = line.strip().split('=')
            if len(parts) == 2 and (parts[0] == 'out_time_ms' or parts[0] == 'out_time_us'):
              if parts[1] == 'N/A':
                continue
              try:
                processed_us = int(parts[1])
                if processed_us != last_processed_us:
                  last_processed_us = processed_us

                processed_seconds = processed_us / 1_000_000.0

                with self.processed_seconds_arr_lock:
                  self.processed_seconds_arr[relative_path] = processed_seconds

                progress = min(100, (processed_seconds / dst_time) * 100) if dst_time > 0 else 0
                progress_bar.set_progress(progress)
                self.master.update_idletasks()
                self.update_total_progress(relative_path)
                logging.debug(f"{relative_path}: processed_us={processed_us}, processed_seconds/dst_time = {processed_seconds:.1f}/{dst_time:.1f} = {(processed_seconds / dst_time * 100):.1f}" )
              except (ValueError, IndexError) as e:
                logging.warning(f"Could not parse progress line: {line.strip()} - {e}")

        except queue.Empty:
          if process.poll() is not None:
            break
          time.sleep(GUI_TIMEOUT)

        # Check for timeout
        if getattr(progress_bar, 'paused', None) and progress_bar.paused.get():
          last_change_time = time.time()
        elif THREAD_PROGRESS_TIMEOUT > 0 and time.time() - last_change_time > THREAD_PROGRESS_TIMEOUT:
          process.kill()
          progress_bar.cancelled.set(True)
          raise TimeoutError(f"Processing timeout. No progress for {THREAD_PROGRESS_TIMEOUT} seconds.")

    except TimeoutError:
      # TimeoutError will be logged/handled by the caller (process_file)
      raise
    except Exception as e:
      logging.exception(f"Unexpected error monitoring progress for {relative_path}: {e}")
      raise
    finally:
      # Check if the process was cancelled
      if not progress_bar.cancelled.get():
        progress_bar.set_progress(100)
        with self.processed_files_lock:
          self.processed_files += 1
      self.master.update_idletasks()
      stdout_thread.join()
      stderr_thread.join()
    return


  #############################################################################
  def update_total_progress(self, relative_path=None):
    """Updates the total progress bar based on cumulative processed size."""
    if self.is_shutting_down:
      return

    current_time = time.time()

    # Only update GUI at specified intervals >= GUI_TIMEOUT
    if not hasattr(self, '_last_progress_update') or \
       (current_time - self._last_progress_update) >= GUI_TIMEOUT:
      self._last_progress_update = current_time

      # Update processed time under lock
      with self.total_dst_seconds_lock:
        total_processed_seconds = sum(self.processed_seconds_arr.values())
      total_progress_percentage = int((total_processed_seconds / self.total_dst_seconds) * 100) if self.total_dst_seconds > 0 else 0
      total_progress_percentage = min(100, total_progress_percentage)
      if relative_path:
        logging.debug(f"{relative_path}: ttl_prcssd_seconds={int(total_processed_seconds)}, ttl_seconds={int(self.total_dst_seconds)}, prgrss={total_progress_percentage}")
      else:
        logging.debug(f"ttl_prcssd_seconds={int(total_processed_seconds)}, ttl_seconds={int(self.total_dst_seconds)}, prgrss={total_progress_percentage}")

      total_progress_message = f"{total_progress_percentage}%  {self.processed_files+self.skipped_files + self.cancelled_files}/{self.total_files}"

      # Wrap GUI updates in try-except
      try:
        self.total_progress.set_progress(total_progress_percentage)
        self.total_progress.set_display_text(total_progress_message)
      except tk.TclError:
        logging.debug("GUI already closed, skipping progress update")
        return

      # When all files processed, set progress to 100% (might be a bit smaller/larger otherwise)
      if self.processed_files + self.skipped_files + self.cancelled_files == self.total_files:
        total_progress_message = f"100%  {self.processed_files+self.skipped_files+self.cancelled_files}/{self.total_files}"
        self.total_progress.set_progress(100)
        self.total_progress.set_display_text(total_progress_message)
        try:
          self.master.after(100, self.finish_processing)
        except tk.TclError:
          logging.debug("GUI already closed, skipping final progress update")


  #############################################################################
  def process_file(self, src_file_path, relative_path, progress_bar):
    """Processes a single audio file, handling potential overwrites."""

    if relative_path in self.processed_files_set:
      return  # Skip if already processed

    self.processed_files_set.add(relative_path)
    process = None  # Define process outside try block
    dst_file_path = None
    try:
      # if dst_file_path is None:  # Skip file
      if self.file_info[relative_path]["skipped"]:
        progress_bar.set_display_text(relative_path)
        progress_bar.set_progress(100)
        return  # Do not process, if the file should be skipped

      resolved_dst_dir = self.resolve_path(self.dst_dir.get())
      dst_file_path = os.path.join(resolved_dst_dir, relative_path)
      dst_file_path = self.handle_overwrite(dst_file_path, relative_path)
      os.makedirs(os.path.dirname(dst_file_path), exist_ok=True)


      # Add the actual destination file path to the set
      self.processed_dst_files_set.add((src_file_path, dst_file_path))
      # Get pre-calculated file info
      file_data = self.file_info[relative_path]
      dst_time = file_data["duration"]

      # Display processed filename in progress bar
      progress_bar.prepare_new_file(os.path.basename(dst_file_path))
      progress_bar.relative_path = relative_path

      # Generate ffmpeg command for video compression
      ffmpeg_command = self.generate_ffmpeg_command(src_file_path, dst_file_path)
      # Start FFMPEG process in binary mode for each file (n_threads)
      process = subprocess.Popen(
        ffmpeg_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # The progress is piped to stdout, so we need to make sure the stderr buffer doesn't fill up
        # We can read it to a devnull to discard it.
        # Note: This requires universal_newlines=False, which is the default.
        # stderr=subprocess.DEVNULL
      )
      # Add process to active processes list
      with self.processes_lock:
        self.active_processes[process.pid] = process
        self.progress_bar_to_pid[progress_bar] = process.pid

      # Monitor and update each audio file processing progress
      self.monitor_progress(process, progress_bar, dst_time, relative_path)

      # Preserve modification time if enabled and process finished successfully
      if self.preserve_timestamps.get() and not progress_bar.cancelled.get() and process.poll() == 0:
        try:
          original_mtime = os.stat(src_file_path).st_mtime
          # Use current access time of the destination file
          current_atime = os.stat(dst_file_path).st_atime
          os.utime(dst_file_path, (current_atime, original_mtime))
          logging.info(f"Preserved modification time for {relative_path}")
        except Exception as e:
          logging.warning(f"Failed to preserve modification time for {relative_path}: {e}")

      self.master.update_idletasks()

      # Remove process from active processes list
      with self.processes_lock:
        if process.pid in self.active_processes:
          del self.active_processes[process.pid]
        if progress_bar in self.progress_bar_to_pid:
          del self.progress_bar_to_pid[progress_bar]


    except Exception as e:
      msg = f"Error processing {relative_path}: {e}"
      logging.exception(msg)
      self.status_update_queue.put(msg)
      self.error_files += 1

      # Wait briefly to ensure ffmpeg process has fully terminated and released the file handle
      if process:
        try:
          process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
          pass

      # Auto-remove the invalid/incomplete output file
      try:
        if dst_file_path and os.path.exists(dst_file_path):
          os.remove(dst_file_path)
          rm_msg = f"Removed incomplete file: {dst_file_path}"
          logging.info(rm_msg)
          self.status_update_queue.put(rm_msg)
      except Exception as rm_e:
        logging.warning(f"Failed to remove incomplete file {dst_file_path}: {rm_e}")

      raise
    finally:
      # Ensure process is removed from active processes even if error occurs
      with self.processes_lock:
        if process and process.pid in self.active_processes:
          del self.active_processes[process.pid]
        if progress_bar in self.progress_bar_to_pid:
            del self.progress_bar_to_pid[progress_bar]
      if not self.is_shutting_down:
        self.update_total_progress(relative_path) # Update total progress after each file


  #############################################################################
  def count_dst_files_sz(self):
    """Calculate the actual size of output files after processing."""
    self.total_dst_sz = 0
    self.total_src_sz = 0
    n_files = 0


    for src_file_path, dst_file_path in self.processed_dst_files_set:
      if os.path.exists(dst_file_path) and os.path.exists(src_file_path):
        self.total_dst_sz += os.stat(dst_file_path).st_size
        self.total_src_sz += os.stat(src_file_path).st_size
        n_files += 1


  #############################################################################
  def queue_media_files(self):
    """Find, count, queue video files, and pre-calculate output sizes."""
    src_dir = self.src_dir.get()
    self.total_files = 0
    self.total_src_sz = 0
    self.queue = queue.Queue()
    self.file_info = {}  # Dictionary to store file info
    self.processed_files_set.clear()
    self.processed_dst_files_set.clear()  # Clear processed destination files
    self.total_dst_seconds = 0

    last_update_time = time.time()

    resolved_src_dir = self.resolve_path(src_dir)
    resolved_dst_dir = self.resolve_path(self.dst_dir.get())

    for root, _, files in os.walk(resolved_src_dir):
      for file in files:
        if file.lower().endswith(VID_EXT):
          full_path = os.path.join(root, file)
          relative_path = os.path.relpath(full_path, resolved_src_dir)
          self.queue.put((full_path, relative_path))
          self.total_files += 1
          file_stat = os.stat(full_path)
          self.total_src_sz += file_stat.st_size

          # Skip existing files
          overwrite_option = self.overwrite_options.get()
          dst_relative_path_base, ext = os.path.splitext(relative_path)
          dst_file_path = os.path.join(resolved_dst_dir, dst_relative_path_base + ext)
          if os.path.exists(dst_file_path) and overwrite_option == "Skip existing files":
            self.skipped_files += 1
            self.file_info[relative_path] = {"duration": 0, "skipped": True}
            self.total_src_sz -= file_stat.st_size  # Exclude skipped file size from total
          else:
            # Get audio file metadata and calculate size
            duration, success = self.get_metadata_info(self.ffmpeg_path.get(), full_path)
            if success:
              duration_tempo = duration/self.tempo.get()
              self.file_info[relative_path] = {"duration": duration_tempo, "skipped": False}
              # logging.debug(f"{relative_path}: dst_est_sz_kbt={dst_est_sz_kbt}")
              dst_seconds = int(duration_tempo)
              self.total_dst_seconds += dst_seconds
              logging.debug(f"{relative_path}: dst_seconds={dst_seconds}")
            else:
              msg = f"Could not get media file metadata for {full_path}"
              logging.error(msg)
              self.status_update_queue.put(msg)
              self.error_files += 1
              # Ensure file_info is populated even on failure to avoid KeyError later
              self.file_info[relative_path] = {"duration": 0, "skipped": True}

          # Update the status_text every second, replacing text (instead of adding new lines)
          current_time = time.time()
          if current_time - last_update_time >= UPDATE_STATUS_TIMEOUT:
            msg = f"{self.total_files} files analyzed, total duration: "
            if (self.total_dst_seconds > 3600):  # > 1 Hour?
              msg += f"{self.total_dst_seconds / (3600):.2f} Hours"
            else:
              msg += f"{self.total_dst_seconds / (60):.2f} Minutes"
            self.update_status(msg, replace=True)
#            logging.info(msg)
            self.master.update_idletasks()
            last_update_time = current_time

    logging.debug(f"total_dst_seconds={self.total_dst_seconds}")
    msg = f"{self.total_files} files analyzed, total duration: "
    if (self.total_dst_seconds > 3600):  # > 1 Hour?
      msg += f"{self.total_dst_seconds / (3600):.2f} Hours"
    else:
      msg += f"{self.total_dst_seconds / (60):.2f} Minutes"

    self.update_status(msg, replace=True)
    logging.info(msg)


  #############################################################################
  def start_process_files_threads(self):
    """Starts the file processing threads."""
    num_threads = min(self.n_threads.get(), self.total_files)
    self.active_threads = num_threads

    for i in range(num_threads):
      thread = threading.Thread(target=self.worker, args=(i,), name=f"Worker-{i}")
      thread.daemon = True  # Make thread daemon so it doesn't prevent program exit
      self.threads.append(thread)
      thread.start()


  #############################################################################
  def worker(self, thread_index):
    """Worker function for each thread, processing files from the queue."""
    progress_bar = self.progress_bars[thread_index]

    while not self.is_shutting_down:  # Check shutdown flag
      try:
        # Reduced timeout to make thread more responsive to shutdown
        file_path, relative_path = self.queue.get(timeout=0.1)

        # Reset progress bar state for the new file (filename part will be updated in process_file)
        # We don't reset progress here, it will be done in process_file along with the brand-new filename.

        # Check shutdown flag immediately after getting item
        if file_path is None or self.is_shutting_down:
          self.queue.task_done()
          break

        self.process_file(file_path, relative_path, progress_bar)
        self.queue.task_done()

        # Check if this was the last file
        if len(self.processed_files_set) >= self.total_files:
          break

      except queue.Empty:
        # Check if all files are processed
        if len(self.processed_files_set) >= self.total_files:
          break
        continue
      except Exception as e:
        # Exceptions are already logged in process_file
        self.queue.task_done()  # Ensure task is marked as done even on error
        continue

    with threading.Lock():  # Use a lock to safely decrement active_threads
      self.active_threads -= 1
      if self.active_threads == 0 and not self.is_shutting_down:
        try:
          self.master.after(100, self.finish_processing)
        except tk.TclError:
          logging.debug("GUI already closed, skipping finish_processing call")


  #############################################################################
  def on_closing(self):
    """Handles window closing event, saving configuration."""
    logging.info("Starting application shutdown sequence...")
    self.is_shutting_down = True
    self.save_config()

    # Kill all FFMPEG processes first
    self.kill_active_processes()

    # Clear the file processing queue and signal threads to stop
    queue_items = 0

    # Clear queue and signal threads in one pass
    while not self.queue.empty():
      try:
        self.queue.get_nowait()
        self.queue.task_done()
        queue_items += 1
      except queue.Empty:
        break

    # Add sentinel values for remaining threads
    for _ in range(len(self.threads)):
      self.queue.put((None, None))

    # Wait for threads with shorter timeout
    for thread in self.threads:
      thread.join(timeout=0.01)
      if thread.is_alive():
        logging.warning(f"Worker thread {thread.name} failed to stop gracefully")

    # Clear status update queue
    while not self.status_update_queue.empty():
      try:
        self.status_update_queue.get_nowait()
        self.status_update_queue.task_done()  # Mark task as done
      except queue.Empty:
        break

    # Stop status update thread
    self.status_update_queue.put(None)
    try:
      self.status_update_thread.join(timeout=0.2)
      if self.status_update_thread.is_alive():
        logging.warning("Status update thread failed to stop gracefully")
    except Exception as e:
      logging.error(f"Error joining status update thread: {e}")

    self.master.destroy()
    logging.info("Application shutdown complete")


  #############################################################################
  def start_processing(self):
    """Starts the audio processing."""
    if not self.validate_tempo():
      return

    # Verify FFMPEG/FFPROBE paths
    success, error_msg = self.check_executables()
    if not success:
      messagebox.showerror("Executable Not Found", error_msg)
      return

    self.status_text.config(state=tk.NORMAL)
    self.status_text.delete(1.0, tk.END)
    self.status_text.config(state=tk.DISABLED)

    self.processing_complete = False
    self.active_threads = 0
    self.processed_files = 0
    self.skipped_files = 0
    self.processed_files_set.clear()
    self.processed_seconds_arr.clear()

    # Remove existing progress bars, before creating new ones
    for progress_bar in self.progress_bars:
      progress_bar.grid_forget()
      progress_bar.destroy()
    self.progress_bars.clear()

    # Remove index labels (used to index progress/threads), before creating new ones
    for label in self.progress_bars_idx:
      label.grid_forget()
      label.destroy()
    self.progress_bars_idx.clear()

    # Find, count and queue for processing all audio files
    self.queue_media_files()
    # Check, if there are no audio files to process
    if self.total_files == 0:
      self.finish_processing(False)
      return

    # Create progress bars dynamically
    n_progress_bars = min(self.total_files, self.n_threads.get())
    self.progress_bars = []
    self.progress_bars_idx = []
    for i in range(n_progress_bars):
      # Create index label
      idx_label = ttk.Label(self.master, text=f"{i+1}")
      idx_label.grid(row=9+i, column=0, sticky=tk.E, padx=5)
      self.progress_bars_idx.append(idx_label)

      # Create progress bar
      progress_bar = CustomProgressBar(self.master, width=1202, height=20)
      progress_bar.grid(row=9 + i, column=1)
      progress_bar.bind("<Button-3>", lambda event, pb=progress_bar: self.toggle_pause(pb))
      progress_bar.bind("<Double-1>", lambda event, pb=progress_bar: self.confirm_and_kill_process(pb))
      self.progress_bars.append(progress_bar)

    # Create overall (total) progress bar
    ttk.Label(self.master, text="Overall progress:").grid(row=8, column=0, sticky=tk.W, padx=5)
    self.total_progress = CustomProgressBar(self.master, use_bold_font=True, width=1202, height=25)
    self.total_progress.grid(row=8, column=1, pady=10)  # Place it above progress bars for processed files
    self.total_progress.set_progress(0)
    self.total_progress.set_display_text("0%  0/0")

    self.run_button.config(state=tk.DISABLED)
    for progress_bar in self.progress_bars:
      progress_bar.set_progress(0)
    self.total_progress.set_display_text("0%  0/0")
    self.total_progress.set_progress(0)

    self.start_time = time.time()
    msg = "Starting processing..."
    self.update_status(msg)
    self.master.update_idletasks()
    logging.info(msg)
    self.start_process_files_threads()


  #############################################################################
  def update_status(self, message, replace=False):
    """Updates the status text area."""
    self.status_text.config(state=tk.NORMAL)  # Enable editing
    if replace:
      self.status_text.delete(1.0, tk.END)
    self.status_text.insert(tk.END, message + "\n")
    self.status_text.see(tk.END)
    self.status_text.config(state=tk.DISABLED)  # Disable editing
#    self.master.update_idletasks()


  #############################################################################
  def finish_processing(self, calc_time=True):
    """Handles processing completion."""
    if self.processing_complete:
      return
    self.processing_complete = True
    #
    processing_time_str = ""
    if (calc_time == True):
      end_time = time.time()
      processing_time = end_time - self.start_time
      # Convert time in seconds to "XX min YY sec" string, e.g. 95 sec = "1 min 35 sec"
      if processing_time < 60:
        processing_time_str += f"{processing_time:.2f} sec"
      else:
        processing_time_str += f"{int(processing_time/60)} min {int(processing_time%60)} sec"
    else:
      processing_time = 0

    # Example msg: "3 Files Total: 1 processed, 1 Skipped, 1 Error. Compression ratio  3.95"
    # Add Total and Processed files
    msg = f"{self.total_files} Files Total: {self.processed_files} Processed"
    # Add non-zero Skipped files
    if self.skipped_files:
      msg += f", {self.skipped_files} Skipped"
    # Add non-zero Error files
    if self.error_files:
      msg += f", {self.error_files} Errors"
    # Add non-zero Cancelled files
    if self.cancelled_files:
      msg += f", {self.cancelled_files} Cancelled"
    # Add Processing time
    if (processing_time != 0) and (self.skipped_files < self.total_files):
      msg += f" in {processing_time_str}."
    # Add Compression Ratio
    self.count_dst_files_sz()
    if self.processed_files > 0 and self.total_dst_sz > 0 and hasattr(self, 'total_src_sz') and self.total_src_sz > 0:
      msg += f" Compression ratio {(self.total_src_sz / self.total_dst_sz):.2f}."

    # Display message
    self.update_status("\n" + msg)
    logging.info(msg)
    self.run_button.config(state=tk.NORMAL)

    # 100%
    if hasattr(self, 'total_progress'):
      total_progress_message = f"100%  {self.processed_files+self.skipped_files+self.cancelled_files}/{self.total_files}"
      self.total_progress.set_progress(100)
      self.total_progress.set_display_text(total_progress_message)

    # Clear the threads list
    self.threads.clear()
    self.master.update_idletasks()


  #############################################################################
  def setup_logging(self, log_level='INFO'):
    """Sets up logging to a file."""
    log_file = DFLT_LOG_FILE

    if log_level.upper() == 'DEBUG':
      logging.basicConfig(filename=log_file, level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s')
    else:  # INFO level
      logging.basicConfig(filename=log_file, level=logging.INFO, format='%(message)s')

    # Add separator and timestamp to the log file
    with open(log_file, 'a') as f:
      timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
      separator = f"\n\n==================== START OF LOG - {timestamp} ====================\n"
      f.write(separator)

    # Flush the log to ensure it's written
    for handler in logging.root.handlers:
      handler.flush()


  #############################################################################
  def validate_tempo(self):
    """Validates the tempo value."""
    try:
      tempo = float(self.tempo.get())
      if tempo <= MIN_TEMPO or tempo > MAX_TEMPO:
        messagebox.showerror("Invalid Tempo", f"Tempo must be greater than {MIN_TEMPO} and less than or equal to {MAX_TEMPO}.")
        return False
      return True
    except ValueError:
      messagebox.showerror("Invalid Tempo", "Please enter a valid number for tempo.")
      return False


  #############################################################################
  def on_tempo_focusout(self, event):
    """Handles tempo entry focus out event, validating the input."""
    if not self.validate_tempo():
      self.tempo.set(DFLT_TEMPO)  # Reset to default if invalid


  #############################################################################
  def on_crf_focusout(self, event):
    """Handles crf entry focus out event, validating the input."""
    try:
      crf_val = int(self.crf.get())
      if crf_val < MIN_CRF or crf_val > MAX_CRF:
        messagebox.showerror("Invalid CRF", f"CRF must be between {MIN_CRF} and {MAX_CRF}.")
        self.crf.set(str(DFLT_CRF))
    except ValueError:
      messagebox.showerror("Invalid CRF", "Please enter a valid integer for CRF.")
      self.crf.set(str(DFLT_CRF))


  #############################################################################
  def on_vf_scale_focusout(self, event):
    """Handles vf_scale entry focus out event, validating the input."""
    try:
      vf_scale_val = float(self.vf_scale.get())
      if vf_scale_val < MIN_VF_SCALE or vf_scale_val > MAX_VF_SCALE:
        messagebox.showerror("Invalid VF Scale", f"VF Scale must be between {MIN_VF_SCALE} and {MAX_VF_SCALE}.")
        self.vf_scale.set(str(DFLT_VF_SCALE))
    except ValueError:
      messagebox.showerror("Invalid VF Scale", "Please enter a valid number for VF Scale.")
      self.vf_scale.set(str(DFLT_VF_SCALE))


  #############################################################################
  def on_audio_bitrate_focusout(self, event):
    """Handles audio_bitrate entry focus out event, validating the input."""
    import re
    val = self.audio_bitrate.get()
    if not val or not re.match(r'^\d+[kKmM]$', val):
      messagebox.showerror("Invalid Audio Bitrate", "Please enter a valid audio bitrate (e.g., 64k, 1M).")
      self.audio_bitrate.set(DFLT_AUDIO_BITRATE)


  #############################################################################
  def process_status_updates(self):
    """Processes status updates from the queue."""
    while True:
      try:
        message = self.status_update_queue.get(timeout=0.1)  # Short timeout to avoid blocking indefinitely
        if message is None: # Check for exit signal
          break
        self.update_status(message)
        self.status_update_queue.task_done()
      except queue.Empty:
        if self.is_shutting_down:  # Check shutdown flag
          break
        continue
      except Exception as e:
        logging.exception("Error in status update thread: %s", e)
        break


  #############################################################################
  def kill_active_processes(self):
    """Terminates all active FFMPEG processes."""
    with self.processes_lock:
      for pid, process in self.active_processes.items():
        try:
          p = psutil.Process(pid)
          if p.status() != psutil.STATUS_ZOMBIE:
            p.kill()  # Force kill
        except psutil.NoSuchProcess:
          logging.warning(f"Process with PID {pid} not found, might have already finished.")
        except Exception as e:
          logging.error(f"Error killing process {pid}: {e}")
      self.active_processes.clear()


  #############################################################################
  def confirm_and_kill_process(self, progress_bar):
    """Confirms and kills a process, then starts the next file."""

    with self.processes_lock:
      pid = self.progress_bar_to_pid.get(progress_bar)
      if not pid:
        return

      filename = progress_bar.filename_var.get()
      try:
        p = psutil.Process(pid)

        # Check current pause state to avoid double-suspending on Windows
        was_paused = progress_bar.paused.get()
        if not was_paused:
          p.suspend()
          progress_bar.paused.set(True)
          progress_bar.draw_progress_bar()

        if messagebox.askyesno("Cancel Processing?", f"Are you sure you want to Cancel process for {filename}?"):
          try:
            p.kill()
            # Wait for the process to terminate to release file locks
            p.wait(timeout=3)
          except psutil.NoSuchProcess:
            # Process already terminated, which is fine.
            pass
          except psutil.TimeoutExpired:
            logging.warning(f"Process {pid} did not terminate within the timeout.")

          progress_bar.cancelled.set(True)
          progress_bar.draw_progress_bar()
          self.cancelled_files += 1
          msg = f"Cancelled processing {filename}"
          logging.info(msg)
          self.status_update_queue.put(msg)

          # Rename the partially processed file
          if progress_bar.relative_path:
            dst_file_path = os.path.join(self.resolve_path(self.dst_dir.get()), progress_bar.relative_path)
            if os.path.exists(dst_file_path):
              base, ext = os.path.splitext(dst_file_path)
              new_path = f"{base}_cancelled{ext}"
              try:
                os.rename(dst_file_path, new_path)
                logging.info(f"Renamed partial file to {new_path}")
              except OSError as e:
                logging.error(f"Failed to rename partial file {dst_file_path}: {e}")

          # Remove the process from active tracking
          if pid in self.active_processes:
            del self.active_processes[pid]
          if progress_bar in self.progress_bar_to_pid:
            del self.progress_bar_to_pid[progress_bar]

          # Since a slot is now free, try to start a new task
          self.start_new_task_if_needed()
        else:
          if not was_paused:
            p.resume()
            progress_bar.paused.set(False)
            progress_bar.draw_progress_bar()

      except psutil.NoSuchProcess:
        logging.warning(f"Process with PID {pid} not found for cancellation.")
      except Exception as e:
        logging.error(f"Error killing process {pid}: {e}")


  #############################################################################
  def start_new_task_if_needed(self):
    """Checks if a new task can be started and starts one."""
    if not self.queue.empty() and self.active_threads < self.n_threads.get():
      # Find a free progress bar
      for i, pb in enumerate(self.progress_bars):
        if pb not in self.progress_bar_to_pid:
          thread = threading.Thread(target=self.worker, args=(i,), name=f"Worker-{i}")
          thread.daemon = True
          self.threads.append(thread)
          thread.start()
          self.active_threads += 1
          break


  #############################################################################
  def toggle_pause(self, progress_bar):
    """Toggles the paused state of a process."""
    with self.processes_lock:
      pid = self.progress_bar_to_pid.get(progress_bar)
      if not pid:
        return

      try:
        p = psutil.Process(pid)
        filename = progress_bar.filename_var.get()
        if progress_bar.paused.get():
          p.resume()
          progress_bar.paused.set(False)
          msg = f"Resumed processing {filename}"
          logging.info(msg)
          self.status_update_queue.put(msg)
        else:
          p.suspend()
          progress_bar.paused.set(True)
          msg = f"Paused processing {filename}"
          logging.info(msg)
          self.status_update_queue.put(msg)
        progress_bar.draw_progress_bar()  # Redraw to reflect color change
      except psutil.NoSuchProcess:
        logging.warning(f"Process with PID {pid} not found for pause/resume.")
      except Exception as e:
        logging.error(f"Error toggling pause for process {pid}: {e}")


###############################################################################
if __name__ == "__main__":
  root = tk.Tk()
  app = VideoProcessor(root)
  root.mainloop()
