#!/usr/bin/env python3
"""
Main Window UI

Main application window for Song Editor 3.
"""

import sys
import os
import logging
import time
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QFileDialog, QProgressBar, QTextEdit,
    QTabWidget, QGroupBox, QGridLayout, QComboBox, QCheckBox,
    QSpinBox, QDoubleSpinBox, QLineEdit, QMessageBox, QStatusBar,
    QMenuBar, QMenu, QToolBar, QApplication, QFrame, QScrollArea
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings, QSize
from PySide6.QtGui import QIcon, QFont, QPixmap, QPalette, QColor, QAction

from ..platform_utils import PlatformUtils, PlatformAwareWidget
from .platform_styles import PlatformStyles

from ..core.audio_processor import AudioProcessor
from ..core.transcriber import Transcriber
from ..core.chord_detector import ChordDetector
from ..core.melody_extractor import MelodyExtractor
from ..export.midi_exporter import MidiExporter
from ..export.ccli_exporter import CCLIExporter
from ..export.json_exporter import JSONExporter
from ..models.song_data import SongData
from ..models.metadata import Metadata, TranscriptionInfo, AudioProcessingInfo
from .lyrics_editor import LyricsEditor
from .enhanced_lyrics_editor import EnhancedLyricsEditor
from .chord_editor import ChordEditor
from .melody_editor import MelodyEditor


class ProcessingThread(QThread):
    """Background thread for audio processing."""
    
    progress_updated = Signal(str, int)
    stage_completed = Signal(str, dict)
    processing_finished = Signal(dict)
    error_occurred = Signal(str)
    
    def __init__(self, audio_file: str, config: Dict[str, Any]):
        super().__init__()
        self.audio_file = audio_file
        self.config = config
        self.song_data = None
        self.timeout_seconds = 1800  # 30 minute timeout for long audio files
        self.start_time = None
    
    def run(self):
        """Run the audio processing pipeline."""
        self.start_time = time.time()
        try:
            # Initialize processors
            audio_processor = AudioProcessor(
                use_demucs=self.config.get('use_demucs', True),
                save_intermediate=self.config.get('save_intermediate', True)
            )
            
            # Determine appropriate model size based on selected model
            selected_model = self.config.get('whisper_model', 'faster-whisper')
            if selected_model == 'faster-whisper':
                model_size = 'base'  # Use base for faster-whisper (fast and accurate)
            elif selected_model == 'openai-whisper':
                model_size = 'large-v2'  # Use large-v2 for openai-whisper (best accuracy)
            else:
                model_size = 'base'  # Default for other models
            
            transcriber = Transcriber(
                model=selected_model,
                model_size=model_size,
                language=self.config.get('language', None)  # None for auto-detection
            )
            
            chord_detector = ChordDetector(
                use_chordino=self.config.get('use_chordino', True),
                chord_simplification=self.config.get('simplify_chords', False),
                preserve_chord_richness=self.config.get('preserve_chord_richness', True)
            )
            
            melody_extractor = MelodyExtractor(
                use_basic_pitch=self.config.get('use_basic_pitch', True),
                min_note_duration=self.config.get('min_note_duration', 0.1)
            )
            
            # Process audio
            self.progress_updated.emit("Loading audio...", 10)
            logging.info(f"Processing audio file: {self.audio_file}")
            audio_data = audio_processor.process(self.audio_file)
            
            # Calculate audio duration and estimated processing time
            audio_duration = len(audio_data['audio']) / audio_data['sample_rate']
            estimated_transcription_time = audio_duration * 0.3  # Rough estimate: 30% of audio duration
            
            logging.info(f"Audio loaded: {len(audio_data['audio'])} samples at {audio_data['sample_rate']} Hz")
            logging.info(f"Audio duration: {audio_duration:.1f} seconds")
            logging.info(f"Estimated transcription time: {estimated_transcription_time:.1f} seconds")
            
            if audio_duration > 300:  # 5 minutes
                logging.warning(f"Long audio file detected ({audio_duration:.1f}s) - transcription may take several minutes")
                self.progress_updated.emit(f"Long audio file ({audio_duration:.0f}s) - this may take a while", 25)
                
                # For very long files, suggest using a smaller model
                if audio_duration > 600:  # 10 minutes
                    logging.warning(f"Very long audio file ({audio_duration:.1f}s) - consider using 'tiny' model for faster processing")
                    self.progress_updated.emit(f"Very long file - using 'tiny' model for speed", 26)
            
            self.progress_updated.emit("Transcribing lyrics... (this may take several minutes)", 30)
            logging.info("Starting transcription...")
            
            # Check for timeout before starting transcription
            elapsed_so_far = time.time() - self.start_time
            if elapsed_so_far > self.timeout_seconds:
                raise TimeoutError(f"Processing timeout exceeded ({elapsed_so_far:.1f}s > {self.timeout_seconds}s)")
            
            logging.info(f"Starting transcription after {elapsed_so_far:.1f}s of processing")
            
            # Simple progress update during transcription
            transcription_start = time.time()
            
            # Simple transcription without signal-based timeout (signals don't work in background threads)
            words = transcriber.transcribe(audio_data['audio'], audio_data['sample_rate'])
            transcription_elapsed = time.time() - transcription_start
            logging.info(f"Transcription completed: {len(words)} words found in {transcription_elapsed:.2f}s")
            
            # Update progress after transcription
            elapsed = time.time() - self.start_time
            logging.info(f"Total processing time so far: {elapsed:.2f} seconds")
            self.progress_updated.emit(f"Transcription completed ({transcription_elapsed:.1f}s)", 40)
            
            self.progress_updated.emit("Detecting chords...", 50)
            
            # Check for timeout before chord detection
            elapsed_so_far = time.time() - self.start_time
            if elapsed_so_far > self.timeout_seconds:
                raise TimeoutError(f"Processing timeout exceeded ({elapsed_so_far:.1f}s > {self.timeout_seconds}s)")
            
            chords = chord_detector.detect(audio_data['audio'], audio_data['sample_rate'])
            
            self.progress_updated.emit("Extracting melody...", 70)
            
            # Check for timeout before melody extraction
            elapsed_so_far = time.time() - self.start_time
            if elapsed_so_far > self.timeout_seconds:
                raise TimeoutError(f"Processing timeout exceeded ({elapsed_so_far:.1f}s > {self.timeout_seconds}s)")
            
            notes = melody_extractor.extract(audio_data['audio'], audio_data['sample_rate'])
            
            self.progress_updated.emit("Finalizing...", 90)
            
            # Create song data
            # Convert dictionary to proper objects
            transcription_info = TranscriptionInfo.from_dict(transcriber.get_model_info())
            audio_processing_info = AudioProcessingInfo.from_dict(audio_processor.get_processing_info())
            
            metadata = Metadata(
                source_audio=self.audio_file,
                transcription=transcription_info,
                audio_processing=audio_processing_info
            )
            
            # Convert dictionaries to proper objects
            from ..models.song_data import Word, Chord, Note
            
            word_objects = [Word.from_dict(word) for word in words]
            chord_objects = [Chord.from_dict(chord) for chord in chords]
            note_objects = [Note.from_dict(note) for note in notes]
            
            # Associate chords with words based on timing
            self._associate_chords_with_words(word_objects, chord_objects)
            
            self.song_data = SongData(
                metadata=metadata.to_dict(),
                words=word_objects,
                chords=chord_objects,
                notes=note_objects
            )
            
            self.progress_updated.emit("Processing complete!", 100)
            self.processing_finished.emit(self.song_data.to_dict())
            
        except Exception as e:
            logging.error(f"Processing error: {e}")
            self.error_occurred.emit(str(e))
    
    def _associate_chords_with_words(self, words, chords):
        """Associate detected chords with words based on timing overlap."""
        if not chords:
            return
        
        for word in words:
            word_mid_time = (word.start + word.end) / 2.0
            
            # Find the chord that overlaps with this word's timing
            best_chord = None
            best_overlap = 0.0
            
            for chord in chords:
                chord_start = chord.start if hasattr(chord, 'start') else 0.0
                chord_end = chord.end if hasattr(chord, 'end') else 0.0
                
                # Check if chord overlaps with word
                if chord_start <= word_mid_time <= chord_end:
                    overlap = min(word.end, chord_end) - max(word.start, chord_start)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_chord = chord
            
            # Assign the best matching chord to the word
            if best_chord:
                if hasattr(best_chord, 'symbol'):
                    word.chord = best_chord.symbol
                elif hasattr(best_chord, 'name'):
                    word.chord = best_chord.name
                else:
                    word.chord = str(best_chord)
                logging.debug(f"Associated chord {word.chord} with word '{word.text}' at {word_mid_time:.2f}s")


class MainWindow(QMainWindow):
    """Main application window with platform-aware design."""
    
    def __init__(self):
        super().__init__()
        
        # Initialize platform-aware widget functionality
        self.platform_utils = PlatformUtils()
        self.platform_aware = PlatformAwareWidget()
        
        self.song_data = None
        self.processing_thread = None
        self.settings = QSettings('SongEditor3', 'SongEditor3')
        
        # Platform-specific setup
        self.setup_platform_specific_behavior()
        self.init_ui()
        self.load_settings()
    
    def setup_platform_specific_behavior(self):
        """Setup platform-specific behavior for the main window."""
        # Set window title and size
        self.setWindowTitle("Song Editor 3")
        
        # Get platform-specific window size
        width, height = self.platform_utils.get_recommended_window_size()
        self.resize(width, height)
        
        # Apply platform-specific stylesheet
        self.setStyleSheet(PlatformStyles.get_main_window_style())
        
        # Platform-specific window flags
        if self.platform_utils.is_mobile():
            # Mobile: full screen or large modal
            self.setWindowFlags(Qt.Window | Qt.WindowMaximizeButtonHint)
        else:
            # Desktop: normal window with minimize/maximize
            self.setWindowFlags(Qt.Window)
        
        # Note: High DPI and touch attributes should be set on QApplication, not QWidget
        # These are handled in the main application setup
    
    def init_ui(self):
        """Initialize the user interface with platform-aware design."""
        # Get platform-specific optimizations
        mobile_opts = PlatformStyles.get_mobile_optimizations()
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create main layout with platform-specific spacing
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(mobile_opts["spacing"])
        main_layout.setContentsMargins(
            mobile_opts["safe_area_margin"],
            mobile_opts["safe_area_margin"],
            mobile_opts["safe_area_margin"],
            mobile_opts["safe_area_margin"]
        )
        
        # Create menu bar (minimal for mobile)
        if not self.platform_utils.is_mobile():
            self.create_menu_bar()
            self.create_toolbar()
        
        # Create main content area
        if self.platform_utils.is_mobile():
            # Mobile: vertical layout with scroll area
            self.create_mobile_ui(main_layout)
        else:
            # Desktop: horizontal splitter layout
            self.create_desktop_ui(main_layout)
        
        # Create status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Create progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
        
        # Set status
        self.status_bar.showMessage("Ready")
    
    def create_mobile_ui(self, main_layout):
        """Create mobile-optimized UI layout."""
        # Create scroll area for mobile
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Create scroll content widget
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(16)  # Mobile spacing
        
        # Add controls at top
        controls_panel = self.create_mobile_controls_panel()
        scroll_layout.addWidget(controls_panel)
        
        # Add tab widget for editors
        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self.create_lyrics_editor(), "Lyrics")
        self.tab_widget.addTab(self.create_chord_editor(), "Chords")
        self.tab_widget.addTab(self.create_melody_editor(), "Melody")
        scroll_layout.addWidget(self.tab_widget)
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
    
    def create_desktop_ui(self, main_layout):
        """Create desktop-optimized UI layout."""
        # Create main splitter
        main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(main_splitter)
        
        # Create left panel (controls and info)
        left_panel = self.create_left_panel()
        main_splitter.addWidget(left_panel)
        
        # Create right panel (editors)
        right_panel = self.create_right_panel()
        main_splitter.addWidget(right_panel)
        
        # Set splitter proportions
        main_splitter.setSizes([300, 900])
    
    def create_mobile_controls_panel(self):
        """Create mobile-optimized controls panel."""
        panel = QGroupBox("Audio Processing")
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)
        
        # File selection
        file_layout = QHBoxLayout()
        self.file_label = QLabel("No file selected")
        self.file_label.setWordWrap(True)
        file_layout.addWidget(self.file_label)
        
        select_button = QPushButton("Select Audio")
        select_button.clicked.connect(self.open_audio_file)
        select_button.setMinimumHeight(48)  # Mobile touch target
        file_layout.addWidget(select_button)
        layout.addLayout(file_layout)
        
        # Processing options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)
        
        # Whisper model selection
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["openai-whisper", "faster-whisper", "whisperx"])
        model_layout.addWidget(self.model_combo)
        options_layout.addLayout(model_layout)
        
        # Content type selection
        content_layout = QHBoxLayout()
        content_layout.addWidget(QLabel("Content:"))
        self.content_combo = QComboBox()
        self.content_combo.addItems(["general", "christian", "gospel", "worship", "hymn", "clean"])
        content_layout.addWidget(self.content_combo)
        options_layout.addLayout(content_layout)
        
        layout.addWidget(options_group)
        
        # Process button
        self.process_button = QPushButton("Process Audio")
        self.process_button.clicked.connect(self.process_audio)
        self.process_button.setMinimumHeight(48)  # Mobile touch target
        layout.addWidget(self.process_button)
        
        return panel
    
    def create_lyrics_editor(self):
        """Create lyrics editor widget with toggle for enhanced mode."""
        from .lyrics_editor import LyricsEditor
        from .enhanced_lyrics_editor import EnhancedLyricsEditor
        
        # Create a container widget
        container = QWidget()
        layout = QVBoxLayout(container)
        
        # Create toggle button
        self.enhanced_mode_toggle = QPushButton("🔧 Switch to Enhanced Mode")
        self.enhanced_mode_toggle.setCheckable(True)
        self.enhanced_mode_toggle.toggled.connect(self.toggle_lyrics_editor_mode)
        layout.addWidget(self.enhanced_mode_toggle)
        
        # Create both editors
        self.basic_lyrics_editor = LyricsEditor()
        self.enhanced_lyrics_editor = EnhancedLyricsEditor()
        
        # Start with basic editor visible
        self.basic_lyrics_editor.show()
        self.enhanced_lyrics_editor.hide()
        
        layout.addWidget(self.basic_lyrics_editor)
        layout.addWidget(self.enhanced_lyrics_editor)
        
        return container
    
    def toggle_lyrics_editor_mode(self, enhanced_mode: bool):
        """Toggle between basic and enhanced lyrics editor modes."""
        if enhanced_mode:
            self.basic_lyrics_editor.hide()
            self.enhanced_lyrics_editor.show()
            self.enhanced_mode_toggle.setText("🔧 Switch to Basic Mode")
            # Transfer any existing lyrics data to enhanced editor
            if hasattr(self.basic_lyrics_editor, 'get_lyrics_text'):
                lyrics_text = self.basic_lyrics_editor.get_lyrics_text()
                if hasattr(self.enhanced_lyrics_editor, 'set_lyrics_text'):
                    self.enhanced_lyrics_editor.set_lyrics_text(lyrics_text)
        else:
            self.enhanced_lyrics_editor.hide()
            self.basic_lyrics_editor.show()
            self.enhanced_mode_toggle.setText("🔧 Switch to Enhanced Mode")
            # Transfer any existing lyrics data to basic editor
            if hasattr(self.enhanced_lyrics_editor, 'get_lyrics_text'):
                lyrics_text = self.enhanced_lyrics_editor.get_lyrics_text()
                if hasattr(self.basic_lyrics_editor, 'set_lyrics_text'):
                    self.basic_lyrics_editor.set_lyrics_text(lyrics_text)
    
    def create_chord_editor(self):
        """Create chord editor widget."""
        from .chord_editor import ChordEditor
        return ChordEditor()
    
    def create_melody_editor(self):
        """Create melody editor widget."""
        from .melody_editor import MelodyEditor
        return MelodyEditor()
    
    def create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('&File')
        
        open_action = QAction('&Open Audio...', self)
        open_action.setShortcut('Ctrl+O')
        open_action.triggered.connect(self.open_audio_file)
        file_menu.addAction(open_action)
        
        save_action = QAction('&Save Song Data...', self)
        save_action.setShortcut('Ctrl+S')
        save_action.triggered.connect(self.save_song_data)
        file_menu.addAction(save_action)
        
        export_menu = file_menu.addMenu('&Export')
        
        export_midi_action = QAction('Export &MIDI...', self)
        export_midi_action.triggered.connect(self.export_midi)
        export_menu.addAction(export_midi_action)
        
        export_ccli_action = QAction('Export &CCLI...', self)
        export_ccli_action.triggered.connect(self.export_ccli)
        export_menu.addAction(export_ccli_action)
        
        export_json_action = QAction('Export &JSON...', self)
        export_json_action.triggered.connect(self.export_json)
        export_menu.addAction(export_json_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction('E&xit', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu('&Edit')
        
        undo_action = QAction('&Undo', self)
        undo_action.setShortcut('Ctrl+Z')
        edit_menu.addAction(undo_action)
        
        redo_action = QAction('&Redo', self)
        redo_action.setShortcut('Ctrl+Y')
        edit_menu.addAction(redo_action)
        
        # View menu
        view_menu = menubar.addMenu('&View')
        
        # Help menu
        help_menu = menubar.addMenu('&Help')
        
        about_action = QAction('&About', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def create_toolbar(self):
        """Create the toolbar."""
        toolbar = QToolBar()
        self.addToolBar(toolbar)
        
        # Open button
        open_btn = QPushButton("Open Audio")
        open_btn.clicked.connect(self.open_audio_file)
        toolbar.addWidget(open_btn)
        
        # Process button
        self.process_btn = QPushButton("Process Audio")
        self.process_btn.clicked.connect(self.process_audio)
        self.process_btn.setEnabled(False)
        toolbar.addWidget(self.process_btn)
        
        toolbar.addSeparator()
        
        # Export buttons
        export_midi_btn = QPushButton("Export MIDI")
        export_midi_btn.clicked.connect(self.export_midi)
        toolbar.addWidget(export_midi_btn)
        
        export_ccli_btn = QPushButton("Export CCLI")
        export_ccli_btn.clicked.connect(self.export_ccli)
        toolbar.addWidget(export_ccli_btn)
    
    def create_left_panel(self):
        """Create the left control panel."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # File info group
        file_group = QGroupBox("File Information")
        file_layout = QGridLayout(file_group)
        
        self.file_label = QLabel("No file selected")
        self.file_label.setWordWrap(True)
        file_layout.addWidget(QLabel("Audio File:"), 0, 0)
        file_layout.addWidget(self.file_label, 0, 1)
        
        self.duration_label = QLabel("--")
        file_layout.addWidget(QLabel("Duration:"), 1, 0)
        file_layout.addWidget(self.duration_label, 1, 1)
        
        layout.addWidget(file_group)
        
        # Processing options group
        options_group = QGroupBox("Processing Options")
        options_layout = QGridLayout(options_group)
        
        # Whisper model
        self.whisper_model_combo = QComboBox()
        self.whisper_model_combo.addItems(['openai-whisper', 'faster-whisper', 'whisperx', 'mlx-whisper'])
        options_layout.addWidget(QLabel("Whisper Model:"), 0, 0)
        options_layout.addWidget(self.whisper_model_combo, 0, 1)
        
        # Chord detection method
        self.chord_method_combo = QComboBox()
        self.chord_method_combo.addItems(['chordino', 'chromagram'])
        options_layout.addWidget(QLabel("Chord Detection:"), 1, 0)
        options_layout.addWidget(self.chord_method_combo, 1, 1)
        
        # Melody extraction method
        self.melody_method_combo = QComboBox()
        self.melody_method_combo.addItems(['basic-pitch', 'crepe'])
        options_layout.addWidget(QLabel("Melody Extraction:"), 2, 0)
        options_layout.addWidget(self.melody_method_combo, 2, 1)
        
        # Use Demucs
        self.use_demucs_check = QCheckBox("Use Demucs (Source Separation)")
        self.use_demucs_check.setChecked(True)
        options_layout.addWidget(self.use_demucs_check, 3, 0, 1, 2)
        
        # Save intermediate files
        self.save_intermediate_check = QCheckBox("Save Intermediate Files")
        self.save_intermediate_check.setChecked(True)
        options_layout.addWidget(self.save_intermediate_check, 4, 0, 1, 2)
        
        layout.addWidget(options_group)
        
        # Song info group
        song_group = QGroupBox("Song Information")
        song_layout = QGridLayout(song_group)
        
        self.title_edit = QLineEdit()
        song_layout.addWidget(QLabel("Title:"), 0, 0)
        song_layout.addWidget(self.title_edit, 0, 1)
        
        self.artist_edit = QLineEdit()
        song_layout.addWidget(QLabel("Artist:"), 1, 0)
        song_layout.addWidget(self.artist_edit, 1, 1)
        
        self.album_edit = QLineEdit()
        song_layout.addWidget(QLabel("Album:"), 2, 0)
        song_layout.addWidget(self.album_edit, 2, 1)
        
        self.genre_edit = QLineEdit()
        song_layout.addWidget(QLabel("Genre:"), 3, 0)
        song_layout.addWidget(self.genre_edit, 3, 1)
        
        layout.addWidget(song_group)
        
        # Statistics group
        stats_group = QGroupBox("Statistics")
        stats_layout = QGridLayout(stats_group)
        
        self.word_count_label = QLabel("0")
        stats_layout.addWidget(QLabel("Words:"), 0, 0)
        stats_layout.addWidget(self.word_count_label, 0, 1)
        
        self.chord_count_label = QLabel("0")
        stats_layout.addWidget(QLabel("Chords:"), 1, 0)
        stats_layout.addWidget(self.chord_count_label, 1, 1)
        
        self.note_count_label = QLabel("0")
        stats_layout.addWidget(QLabel("Notes:"), 2, 0)
        stats_layout.addWidget(self.note_count_label, 2, 1)
        
        layout.addWidget(stats_group)
        
        layout.addStretch()
        
        return panel
    
    def create_right_panel(self):
        """Create the right editor panel."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        
        # Lyrics editor tab with enhanced toggle
        self.lyrics_editor_container = self.create_lyrics_editor()
        self.tab_widget.addTab(self.lyrics_editor_container, "Lyrics")
        
        # Chord editor tab
        self.chord_editor = ChordEditor()
        self.tab_widget.addTab(self.chord_editor, "Chords")
        
        # Melody editor tab
        self.melody_editor = MelodyEditor()
        self.tab_widget.addTab(self.melody_editor, "Melody")
        
        layout.addWidget(self.tab_widget)
        
        return panel
    
    def open_audio_file(self):
        """Open an audio file for processing with platform-aware dialog."""
        # Use platform-specific file dialog options
        if self.platform_utils.should_use_native_dialogs():
            # Use native file dialog
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Open Audio File",
                "",
                "Audio Files (*.mp3 *.wav *.m4a *.flac *.ogg *.aac *.opus);;All Files (*)"
            )
        else:
            # Use custom file dialog for mobile platforms
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Audio File",
                "",
                "Audio Files (*.mp3 *.wav *.m4a *.flac *.ogg *.aac *.opus);;All Files (*)",
                options=QFileDialog.DontUseNativeDialog
            )
        
        if file_path:
            self.audio_file_path = file_path
            self.file_label.setText(Path(file_path).name)
            self.process_btn.setEnabled(True)
            self.status_bar.showMessage(f"Loaded: {Path(file_path).name}")
            
            # Auto-load existing .song_data file if it exists
            self.check_and_load_existing_song_data(file_path)
    
    def check_and_load_existing_song_data(self, audio_file_path: str):
        """Check for and load existing .song_data file associated with the audio file."""
        from pathlib import Path
        import os
        
        # Get the base name without extension and add .song_data
        audio_path = Path(audio_file_path)
        song_data_path = audio_path.with_suffix('.song_data')
        
        if song_data_path.exists():
            try:
                # Import the necessary modules
                from ..export.json_exporter import JSONExporter
                from ..models.song_data import SongData
                
                # Load the existing song data
                with open(song_data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Create SongData object from the loaded data
                self.song_data = SongData.from_dict(data)
                
                # Populate the editors with the existing data
                if hasattr(self, 'basic_lyrics_editor') and self.basic_lyrics_editor:
                    self.basic_lyrics_editor.set_song_data(self.song_data)
                
                if hasattr(self, 'enhanced_lyrics_editor') and self.enhanced_lyrics_editor:
                    self.enhanced_lyrics_editor.set_song_data(self.song_data)
                    self.enhanced_lyrics_editor.set_audio_path(audio_file_path)
                
                if hasattr(self, 'chord_editor') and self.chord_editor:
                    self.chord_editor.set_song_data(self.song_data)
                
                if hasattr(self, 'melody_editor') and self.melody_editor:
                    self.melody_editor.set_song_data(self.song_data)
                
                # Update status
                self.status_bar.showMessage(f"Loaded existing song data: {song_data_path.name}")
                
                # Enable save functionality
                if hasattr(self, 'save_action'):
                    self.save_action.setEnabled(True)
                
                # Auto-save to ensure the data is preserved with any updates
                self.save_song_data_auto()
                
                logging.info(f"Successfully loaded existing song data from {song_data_path}")
                
            except Exception as e:
                logging.error(f"Failed to load existing song data from {song_data_path}: {e}")
                self.status_bar.showMessage(f"Failed to load song data: {e}")
    
    def process_audio(self):
        """Process the loaded audio file."""
        if not hasattr(self, 'audio_file_path'):
            QMessageBox.warning(self, "No File", "Please select an audio file first.")
            return
        
        # Get processing configuration
        config = {
            'whisper_model': self.whisper_model_combo.currentText(),
            'chordino': self.chord_method_combo.currentText(),
            'melody_method': self.melody_method_combo.currentText(),
            'use_demucs': self.use_demucs_check.isChecked(),
            'save_intermediate': self.save_intermediate_check.isChecked(),
            'language': None  # None for auto-detection
        }
        
        # Start processing thread
        self.processing_thread = ProcessingThread(self.audio_file_path, config)
        self.processing_thread.progress_updated.connect(self.update_progress)
        self.processing_thread.stage_completed.connect(self.stage_completed)
        self.processing_thread.processing_finished.connect(self.processing_finished)
        self.processing_thread.error_occurred.connect(self.processing_error)
        
        # Update UI
        self.process_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_bar.showMessage("Processing audio...")
        
        # Start processing
        self.processing_thread.start()
    
    def update_progress(self, message: str, value: int):
        """Update the progress bar."""
        self.progress_bar.setValue(value)
        self.status_bar.showMessage(message)
    
    def stage_completed(self, stage: str, data: Dict[str, Any]):
        """Handle stage completion."""
        logging.info(f"Stage completed: {stage}")
    
    def processing_finished(self, song_data: Dict[str, Any]):
        """Handle processing completion."""
        self.song_data = SongData.from_dict(song_data)
        
        # Update song information
        if self.song_data.metadata.get('title'):
            self.title_edit.setText(self.song_data.metadata['title'])
        if self.song_data.metadata.get('artist'):
            self.artist_edit.setText(self.song_data.metadata['artist'])
        if self.song_data.metadata.get('album'):
            self.album_edit.setText(self.song_data.metadata['album'])
        if self.song_data.metadata.get('genre'):
            self.genre_edit.setText(self.song_data.metadata['genre'])
        
        # Update statistics
        self.word_count_label.setText(str(self.song_data.get_word_count()))
        self.chord_count_label.setText(str(self.song_data.get_chord_count()))
        self.note_count_label.setText(str(self.song_data.get_note_count()))
        
        # Update duration
        duration = self.song_data.get_duration()
        if duration > 0:
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            self.duration_label.setText(f"{minutes}:{seconds:02d}")
        
        # Update editors
        self.basic_lyrics_editor.set_song_data(self.song_data)
        self.enhanced_lyrics_editor.set_song_data(self.song_data)
        if hasattr(self, 'audio_file_path') and self.audio_file_path:
            self.enhanced_lyrics_editor.set_audio_path(self.audio_file_path)
        self.chord_editor.set_song_data(self.song_data)
        self.melody_editor.set_song_data(self.song_data)
        
        # Update UI
        self.process_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_bar.showMessage("Processing complete!")
        
        # Auto-save the song data
        if self.save_song_data_auto():
            self.status_bar.showMessage("Processing complete! Song data auto-saved.")
        else:
            self.status_bar.showMessage("Processing complete! Failed to auto-save song data.")
        
        # Show completion message
        QMessageBox.information(
            self,
            "Processing Complete",
            f"Successfully processed audio file.\n"
            f"Words: {self.song_data.get_word_count()}\n"
            f"Chords: {self.song_data.get_chord_count()}\n"
            f"Notes: {self.song_data.get_note_count()}\n\n"
            f"Song data has been auto-saved."
        )
    
    def processing_error(self, error_message: str):
        """Handle processing error."""
        self.process_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_bar.showMessage("Processing failed!")
        
        QMessageBox.critical(
            self,
            "Processing Error",
            f"An error occurred during processing:\n{error_message}"
        )
    
    def save_song_data(self):
        """Save the song data to a JSON file."""
        if not self.song_data:
            QMessageBox.warning(self, "No Data", "No song data to save.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Song Data",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            exporter = JSONExporter()
            if exporter.export(self.song_data.to_dict(), file_path):
                self.status_bar.showMessage(f"Saved: {Path(file_path).name}")
            else:
                QMessageBox.critical(self, "Save Error", "Failed to save song data.")
    
    def save_song_data_auto(self):
        """Auto-save song data with the same name as the audio file."""
        if not self.song_data or not hasattr(self, 'audio_file_path'):
            return False
        
        try:
            from pathlib import Path
            audio_path = Path(self.audio_file_path)
            song_data_path = audio_path.with_suffix('.song_data')
            
            exporter = JSONExporter()
            if exporter.export(self.song_data.to_dict(), str(song_data_path)):
                logging.info(f"Auto-saved song data to {song_data_path}")
                return True
            else:
                logging.error(f"Failed to auto-save song data to {song_data_path}")
                return False
        except Exception as e:
            logging.error(f"Error auto-saving song data: {e}")
            return False
    
    def export_midi(self):
        """Export song data to MIDI format."""
        if not self.song_data:
            QMessageBox.warning(self, "No Data", "No song data to export.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export MIDI",
            "",
            "MIDI Files (*.mid);;All Files (*)"
        )
        
        if file_path:
            exporter = MidiExporter()
            if exporter.export(self.song_data.to_dict(), file_path):
                self.status_bar.showMessage(f"Exported MIDI: {Path(file_path).name}")
            else:
                QMessageBox.critical(self, "Export Error", "Failed to export MIDI.")
    
    def export_ccli(self):
        """Export song data to CCLI format."""
        if not self.song_data:
            QMessageBox.warning(self, "No Data", "No song data to export.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export CCLI",
            "",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            exporter = CCLIExporter()
            if exporter.export(self.song_data.to_dict(), file_path):
                self.status_bar.showMessage(f"Exported CCLI: {Path(file_path).name}")
            else:
                QMessageBox.critical(self, "Export Error", "Failed to export CCLI.")
    
    def export_json(self):
        """Export song data to JSON format."""
        if not self.song_data:
            QMessageBox.warning(self, "No Data", "No song data to export.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export JSON",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            exporter = JSONExporter()
            if exporter.export(self.song_data.to_dict(), file_path):
                self.status_bar.showMessage(f"Exported JSON: {Path(file_path).name}")
            else:
                QMessageBox.critical(self, "Export Error", "Failed to export JSON.")
    
    def show_about(self):
        """Show the about dialog."""
        QMessageBox.about(
            self,
            "About Song Editor 3",
            "Song Editor 3\n\n"
            "A comprehensive audio processing and song analysis tool.\n\n"
            "Features:\n"
            "• Audio transcription with multiple Whisper models\n"
            "• Chord detection with Chordino\n"
            "• Melody extraction with Basic Pitch/CREPE\n"
            "• Source separation with Demucs\n"
            "• Export to MIDI, CCLI, and JSON formats\n\n"
            "Version 3.0.0"
        )
    
    def load_settings(self):
        """Load application settings."""
        # Load window geometry
        geometry = self.settings.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)
        
        # Load processing options
        whisper_model = self.settings.value('whisper_model', 'openai-whisper')
        index = self.whisper_model_combo.findText(whisper_model)
        if index >= 0:
            self.whisper_model_combo.setCurrentIndex(index)
        
        chord_method = self.settings.value('chord_method', 'chordino')
        index = self.chord_method_combo.findText(chord_method)
        if index >= 0:
            self.chord_method_combo.setCurrentIndex(index)
        
        melody_method = self.settings.value('melody_method', 'basic-pitch')
        index = self.melody_method_combo.findText(melody_method)
        if index >= 0:
            self.melody_method_combo.setCurrentIndex(index)
        
        self.use_demucs_check.setChecked(self.settings.value('use_demucs', True, type=bool))
        self.save_intermediate_check.setChecked(self.settings.value('save_intermediate', True, type=bool))
    
    def save_settings(self):
        """Save application settings."""
        # Save window geometry
        self.settings.setValue('geometry', self.saveGeometry())
        
        # Save processing options
        self.settings.setValue('whisper_model', self.whisper_model_combo.currentText())
        self.settings.setValue('chord_method', self.chord_method_combo.currentText())
        self.settings.setValue('melody_method', self.melody_method_combo.currentText())
        self.settings.setValue('use_demucs', self.use_demucs_check.isChecked())
        self.settings.setValue('save_intermediate', self.save_intermediate_check.isChecked())
    
    def closeEvent(self, event):
        """Handle window close event."""
        self.save_settings()
        event.accept()


