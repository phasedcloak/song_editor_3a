import os
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel, 
    QPushButton, QScrollArea, QFrame, QSplitter, QCheckBox,
    QToolTip, QApplication, QSizePolicy, QComboBox, QSlider
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import (
    QTextCursor, QTextCharFormat, QColor, QFont, QPalette,
    QTextDocument, QTextBlockFormat, QTextBlock, QTextOption
)

import cmudict
import pronouncing
import nltk
from collections import Counter

from ..models.lyrics import WordRow
from ..core.audio_player import AudioPlayer


@dataclass
class RhymeInfo:
    """Information about rhyming words"""
    word: str
    pronunciation: List[str]
    rhyme_type: str  # 'perfect', 'near', 'none'
    rhyme_group: str  # Group identifier for same color


class SyllableCounter:
    """Professional syllable counting using cmudict"""
    
    def __init__(self):
        self.cmu = cmudict.dict()
        self.cache = {}
    
    def count_syllables(self, word: str) -> int:
        """Count syllables in a word using cmudict"""
        if word in self.cache:
            return self.cache[word]
        
        # Clean the word
        clean_word = re.sub(r'[^\w\s]', '', word.lower())
        
        if clean_word in self.cmu:
            # Get the first pronunciation
            pronunciation = self.cmu[clean_word][0]
            # Count syllables (each vowel sound is a syllable)
            syllable_count = len([p for p in pronunciation if p[-1].isdigit()])
            self.cache[word] = syllable_count
            return syllable_count
        else:
            # Fallback: estimate syllables by counting vowel groups
            vowel_groups = len(re.findall(r'[aeiouy]+', clean_word))
            self.cache[word] = max(1, vowel_groups)
            return max(1, vowel_groups)


class WordFrequencyAnalyzer:
    """Analyze word frequency using NLTK corpora"""
    
    def __init__(self):
        self.frequency_cache = {}
        self._init_frequency_data()
    
    def _init_frequency_data(self):
        """Initialize word frequency data from NLTK"""
        try:
            # Try to download required NLTK data if not present
            try:
                nltk.data.find('corpora/brown')
            except LookupError:
                nltk.download('brown', quiet=True)
            
            # Build frequency distribution from Brown corpus
            from nltk.corpus import brown
            words = [word.lower() for word in brown.words()]
            self.freq_dist = Counter(words)
            
        except Exception as e:
            print(f"Warning: Could not load NLTK frequency data: {e}")
            # Fallback to empty frequency distribution
            self.freq_dist = Counter()
    
    def get_frequency(self, word: str) -> int:
        """Get frequency count for a word"""
        if word in self.frequency_cache:
            return self.frequency_cache[word]
        
        clean_word = word.lower().strip()
        freq = self.freq_dist.get(clean_word, 0)
        self.frequency_cache[word] = freq
        return freq
    
    def sort_by_frequency(self, words: list) -> list:
        """Sort words by frequency (most common first)"""
        return sorted(words, key=self.get_frequency, reverse=True)


class RhymeAnalyzer:
    """Analyze rhyming patterns using pronouncing library"""
    
    def __init__(self):
        self.cache = {}
        self.frequency_analyzer = WordFrequencyAnalyzer()
    
    def get_pronunciation(self, word: str) -> List[str]:
        """Get pronunciation for a word"""
        if word in self.cache:
            return self.cache[word]
        
        clean_word = re.sub(r'[^\w\s]', '', word.lower())
        pronunciation = pronouncing.phones_for_word(clean_word)
        
        if pronunciation:
            self.cache[word] = pronunciation[0]
            return pronunciation[0]
        else:
            # Fallback: return empty pronunciation
            self.cache[word] = ""
            return ""
    
    def rhyme_key(self, word: str) -> str:
        """Create a stable rhyme key for a word"""
        try:
            clean_word = re.sub(r'[^A-Za-z]', '', word.lower())
            if not clean_word:
                return ""
            phones = pronouncing.phones_for_word(clean_word)
            if phones:
                try:
                    from pronouncing import rhyming_part
                    key = rhyming_part(phones[0])
                    return key or ""
                except Exception:
                    pass
            # Fallback: last stressed-ish vowel cluster + coda
            return clean_word[-3:] if len(clean_word) >= 3 else clean_word
        except Exception:
            return word[-3:] if len(word) >= 3 else word
    
    def near_rhyme_key(self, word: str) -> str:
        """Create a near rhyme key for a word (based on final vowel sound)"""
        try:
            clean_word = re.sub(r'[^A-Za-z]', '', word.lower())
            if not clean_word:
                return ""
            phones = pronouncing.phones_for_word(clean_word)
            if phones:
                # Extract the last vowel sound
                phone_list = phones[0].split()
                for phone in reversed(phone_list):
                    if any(char.isdigit() for char in phone):  # Vowel sound
                        # Remove stress markers for comparison
                        vowel_clean = ''.join(c for c in phone if not c.isdigit())
                        return vowel_clean
            # Fallback: last vowel cluster
            vowel_groups = re.findall(r'[aeiouy]+', clean_word)
            if vowel_groups:
                return vowel_groups[-1]
            return clean_word[-2:] if len(clean_word) >= 2 else clean_word
        except Exception:
            return word[-2:] if len(word) >= 2 else word
    
    def are_perfect_rhymes(self, word1: str, word2: str) -> bool:
        """Check if two words are perfect rhymes"""
        if word1 == word2:
            return False
        
        # Get rhymes for word1 and check if word2 is in the list
        rhymes_list = pronouncing.rhymes(word1)
        return word2.lower() in [r.lower() for r in rhymes_list]
    
    def are_near_rhymes(self, word1: str, word2: str) -> bool:
        """Check if two words are near rhymes (assonance)"""
        if word1 == word2:
            return False
        
        # Get pronunciations
        pron1 = pronouncing.phones_for_word(word1)
        pron2 = pronouncing.phones_for_word(word2)
        
        if not pron1 or not pron2:
            return False
        
        # Use a simpler approach: check if they share the same final stressed vowel
        try:
            # Get the rhyming parts
            rhyme1 = pronouncing.rhyming_part(pron1[0])
            rhyme2 = pronouncing.rhyming_part(pron2[0])
            
            # If they have the same rhyming part, they're perfect rhymes, not near rhymes
            if rhyme1 == rhyme2 and rhyme1:
                return False
            
            # For near rhymes, check if they end with similar vowel sounds
            # Extract the last vowel sound from each pronunciation
            phones1 = pron1[0].split()
            phones2 = pron2[0].split()
            
            last_vowel1 = None
            last_vowel2 = None
            
            # Find the last vowel sound in each word
            for phone in reversed(phones1):
                if any(char.isdigit() for char in phone):  # Vowel sound
                    last_vowel1 = phone
                    break
            
            for phone in reversed(phones2):
                if any(char.isdigit() for char in phone):  # Vowel sound
                    last_vowel2 = phone
                    break
            
            # Check if they have the same final vowel sound (ignoring stress)
            if last_vowel1 and last_vowel2:
                # Remove stress markers for comparison
                vowel1_clean = ''.join(c for c in last_vowel1 if not c.isdigit())
                vowel2_clean = ''.join(c for c in last_vowel2 if not c.isdigit())
                
                # Only consider them near rhymes if they have the same final vowel
                # AND they're not already perfect rhymes
                if vowel1_clean == vowel2_clean:
                    # Additional check: make sure they're not too similar
                    # If they share the same rhyme key, they're perfect rhymes, not near rhymes
                    key1 = self.rhyme_key(word1)
                    key2 = self.rhyme_key(word2)
                    if key1 == key2 and key1:
                        return False
                    return True
            
            return False
            
        except Exception:
            return False
    
    def find_rhymes(self, target_word: str, word_list: List[str]) -> Dict[str, List[str]]:
        """Find perfect and near rhymes for a target word"""
        perfect_rhymes = []
        near_rhymes = []
        
        for word in word_list:
            if word.lower() == target_word.lower():
                continue
            
            if self.are_perfect_rhymes(target_word, word):
                perfect_rhymes.append(word)
            elif self.are_near_rhymes(target_word, word):
                near_rhymes.append(word)
        
        return {
            'perfect': perfect_rhymes,
            'near': near_rhymes
        }
    
    def dict_perfect_rhymes(self, target_word: str) -> List[str]:
        """Return ALL perfect rhymes from the CMU dict via pronouncing.rhymes, sorted by frequency"""
        clean_word = re.sub(r'[^\w\s]', '', target_word.lower())
        try:
            rhymes = pronouncing.rhymes(clean_word)
            # Sort by frequency (most common first)
            return self.frequency_analyzer.sort_by_frequency(rhymes)
        except Exception:
            return []
    
    def dict_near_rhymes(self, target_word: str) -> List[str]:
        """Return ALL near rhymes using stress pattern similarity from CMU dict, sorted by frequency"""
        clean_word = re.sub(r'[^\w\s]', '', target_word.lower())
        try:
            stresses_list = pronouncing.stresses_for_word(clean_word)
            if not stresses_list:
                return []
            stress = stresses_list[0]
            candidates = pronouncing.search_stresses(stress)
            perfect = set(w.lower() for w in pronouncing.rhymes(clean_word))
            result = []
            for w in candidates:
                wl = w.lower()
                if wl == clean_word:
                    continue
                if wl in perfect:
                    continue
                result.append(w)
            # Deduplicate while preserving order
            seen = set()
            deduped = []
            for w in result:
                if w.lower() in seen:
                    continue
                seen.add(w.lower())
                deduped.append(w)
            # Sort by frequency (most common first)
            return self.frequency_analyzer.sort_by_frequency(deduped)
        except Exception:
            return []


class SyllablePanel(QWidget):
    """Left panel showing syllable counts for each line"""
    
    def __init__(self):
        super().__init__()
        self.syllable_counter = SyllableCounter()
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Add top margin to match the control bar height above the main editor
        layout.setContentsMargins(5, 60, 5, 5)  # Top margin of 60px to match control bar
        
        # Syllable counts
        self.counts_text = QTextEdit()
        self.counts_text.setMaximumWidth(100)
        self.counts_text.setReadOnly(True)
        self.counts_text.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                font-family: Arial;
                font-size: 16px;
                font-weight: normal;
                line-height: 1.4;
                padding: 8px;
            }
        """)
        layout.addWidget(self.counts_text)
    
    def update_counts(self, text: str):
        """Update syllable counts for the given text"""
        lines = text.split('\n')
        counts = []
        
        for line in lines:
            if line.strip():
                # Remove chord annotations like [C], [Am], etc.
                line_without_chords = line
                while '[' in line_without_chords and ']' in line_without_chords:
                    start = line_without_chords.find('[')
                    end = line_without_chords.find(']', start)
                    if end == -1:
                        break
                    line_without_chords = line_without_chords[:start] + line_without_chords[end+1:]
                
                words = re.findall(r'\b\w+\b', line_without_chords)
                total_syllables = sum(self.syllable_counter.count_syllables(word) for word in words)
                counts.append(f"{total_syllables:2d}")
            else:
                counts.append("")
        
        self.counts_text.setPlainText('\n'.join(counts))
    
    def sync_syllable_scroll(self, value: int):
        """Sync scroll position with main editor"""
        self.counts_text.verticalScrollBar().setValue(value)


class RhymePanel(QWidget):
    """Right panel showing rhyming suggestions"""
    
    def __init__(self):
        super().__init__()
        self.rhyme_analyzer = RhymeAnalyzer()
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Title
        title = QLabel("Rhyme Suggestions")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        # Selected word
        self.selected_word_label = QLabel("Double-click a word")
        self.selected_word_label.setStyleSheet("font-style: italic; color: #666;")
        layout.addWidget(self.selected_word_label)
        
        # Perfect rhymes
        layout.addWidget(QLabel("Perfect Rhymes:"))
        self.perfect_rhymes_text = QTextEdit()
        self.perfect_rhymes_text.setMaximumHeight(100)
        self.perfect_rhymes_text.setReadOnly(True)
        layout.addWidget(self.perfect_rhymes_text)
        
        # Perfect rhymes with count control
        perfect_layout = QHBoxLayout()
        perfect_layout.addWidget(QLabel("Perfect Rhymes:"))
        self.perfect_rhyme_count_slider = QSlider(Qt.Horizontal)
        self.perfect_rhyme_count_slider.setMinimum(5)
        self.perfect_rhyme_count_slider.setMaximum(100)
        self.perfect_rhyme_count_slider.setValue(20)
        self.perfect_rhyme_count_slider.setTickPosition(QSlider.TicksBelow)
        self.perfect_rhyme_count_slider.setTickInterval(10)
        self.perfect_rhyme_count_slider.valueChanged.connect(self.on_rhyme_count_changed)
        perfect_layout.addWidget(self.perfect_rhyme_count_slider)
        self.perfect_rhyme_count_label = QLabel("20")
        self.perfect_rhyme_count_label.setMinimumWidth(30)
        perfect_layout.addWidget(self.perfect_rhyme_count_label)
        layout.addLayout(perfect_layout)
        
        self.perfect_rhymes_text = QTextEdit()
        self.perfect_rhymes_text.setMaximumHeight(100)
        self.perfect_rhymes_text.setReadOnly(True)
        layout.addWidget(self.perfect_rhymes_text)
        
        # Near rhymes with count control
        near_layout = QHBoxLayout()
        near_layout.addWidget(QLabel("Near Rhymes:"))
        self.near_rhyme_count_slider = QSlider(Qt.Horizontal)
        self.near_rhyme_count_slider.setMinimum(5)
        self.near_rhyme_count_slider.setMaximum(100)
        self.near_rhyme_count_slider.setValue(20)
        self.near_rhyme_count_slider.setTickPosition(QSlider.TicksBelow)
        self.near_rhyme_count_slider.setTickInterval(10)
        self.near_rhyme_count_slider.valueChanged.connect(self.on_rhyme_count_changed)
        near_layout.addWidget(self.near_rhyme_count_slider)
        self.near_rhyme_count_label = QLabel("20")
        self.near_rhyme_count_label.setMinimumWidth(30)
        near_layout.addWidget(self.near_rhyme_count_label)
        layout.addLayout(near_layout)
        
        self.near_rhymes_text = QTextEdit()
        self.near_rhymes_text.setMaximumHeight(100)
        self.near_rhymes_text.setReadOnly(True)
        layout.addWidget(self.near_rhymes_text)
    
    def on_rhyme_count_changed(self):
        """Handle rhyme count slider changes"""
        # Update labels
        perfect_count = self.perfect_rhyme_count_slider.value()
        near_count = self.near_rhyme_count_slider.value()
        self.perfect_rhyme_count_label.setText(str(perfect_count))
        self.near_rhyme_count_label.setText(str(near_count))
        
        # Re-update rhymes if we have a current word
        if hasattr(self, 'current_word') and self.current_word:
            self.update_rhymes(self.current_word, [])
    
    def update_rhymes(self, word: str, all_words: List[str]):
        """Update rhyme suggestions for the selected word"""
        self.current_word = word  # Store current word for slider updates
        self.selected_word_label.setText(f"Selected: {word}")
        
        # Get count limits from sliders
        perfect_count = self.perfect_rhyme_count_slider.value()
        near_count = self.near_rhyme_count_slider.value()
        
        # Dictionary-based rhymes (CMU dict via pronouncing) - Limited by slider, sorted by frequency
        perfect_rhymes = self.rhyme_analyzer.dict_perfect_rhymes(word)
        if perfect_rhymes:
            # Limit by slider value
            limited_perfect = perfect_rhymes[:perfect_count]
            rhyme_text = ', '.join(limited_perfect)
            if len(perfect_rhymes) > perfect_count:
                rhyme_text += f"... ({len(perfect_rhymes)} total, showing {perfect_count}, sorted by frequency)"
            else:
                rhyme_text += f" ({len(perfect_rhymes)} total, sorted by frequency)"
            self.perfect_rhymes_text.setPlainText(rhyme_text)
        else:
            self.perfect_rhymes_text.setPlainText("None found")
        
        # Dictionary-based near rhymes (stress-pattern similarity) - Limited by slider, sorted by frequency
        near_rhymes = self.rhyme_analyzer.dict_near_rhymes(word)
        if near_rhymes:
            # Limit by slider value
            limited_near = near_rhymes[:near_count]
            rhyme_text = ', '.join(limited_near)
            if len(near_rhymes) > near_count:
                rhyme_text += f"... ({len(near_rhymes)} total, showing {near_count}, sorted by frequency)"
            else:
                rhyme_text += f" ({len(near_rhymes)} total, sorted by frequency)"
            self.near_rhymes_text.setPlainText(rhyme_text)
        else:
            self.near_rhymes_text.setPlainText("None found")


class AudioPlaybackThread(QThread):
    """Thread for playing audio segments"""
    
    def __init__(self, audio_path: str, start_time: float, duration: float):
        super().__init__()
        self.audio_path = audio_path
        self.start_time = start_time
        self.duration = duration
        self.player = None
    
    def run(self):
        """Play audio segment"""
        try:
            from ..core.audio_player import AudioPlayer
            self.player = AudioPlayer()
            self.player.load(self.audio_path)
            self.player.play_segment(self.start_time, self.start_time + self.duration)
            # Wait for playback to complete
            import time
            time.sleep(self.duration)
        except Exception as e:
            print(f"Audio playback error: {e}")


class EnhancedLyricsEditor(QWidget):
    """Enhanced lyrics editor with multi-line support, syllable counting, and rhyming"""
    
    lyrics_changed = Signal(str)
    play_audio_requested = Signal(float, float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.audio_path = None
        self.lyrics_data = []
        self.rhyme_analyzer = RhymeAnalyzer()
        self.syllable_counter = SyllableCounter()
        self.playback_thread = None
        self.color_mode = "confidence"  # "confidence" or "rhyme"
        self.rhyme_groups = {}
        self.near_rhyme_groups = {}
        self._rhyme_key_cache = {}
        self._near_key_cache = {}
        self._updating_text = False  # Flag to prevent recursion
        self.time_window = 2.0  # Default time window for audio playback
        # Debounce timer for heavy analysis/formatting
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._analyze_and_color)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # Create splitter for three panels
        self.splitter = QSplitter(Qt.Horizontal)
        
        # Create a container widget that holds both syllable panel and main content
        # This ensures they start at the same vertical position
        self.content_container = QWidget()
        content_layout = QHBoxLayout(self.content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(5)
        
        # Left panel: Syllable counts - add top margin to match the control bar height
        self.syllable_panel = SyllablePanel()
        content_layout.addWidget(self.syllable_panel)
        
        # Center panel: Main lyrics editor
        self.lyrics_panel = self.create_lyrics_panel()
        content_layout.addWidget(self.lyrics_panel)
        
        self.splitter.addWidget(self.content_container)
        
        # Right panel: Rhyming suggestions
        self.rhyme_panel = RhymePanel()
        self.splitter.addWidget(self.rhyme_panel)
        
        # Set initial splitter proportions (center gets most space)
        self.splitter.setSizes([500, 300])
        # Set stretch factors: 70% center, 30% right panel
        self.splitter.setStretchFactor(0, 7)  # Center container (70% equivalent)
        self.splitter.setStretchFactor(1, 3)  # Right panel (30% equivalent)
        # Prevent center pane from collapsing
        try:
            self.splitter.setCollapsible(0, False)
            self.splitter.setCollapsible(1, True)
        except Exception:
            pass
        
        layout.addWidget(self.splitter)
        
        # Ensure all widgets are visible
        self.syllable_panel.show()
        self.lyrics_panel.show()
        self.rhyme_panel.show()
        self.content_container.show()
        self.splitter.show()
        
        # Connect text editor scrolling to syllable panel (after UI is set up)
        self.text_edit.verticalScrollBar().valueChanged.connect(self.on_text_scroll)
        
        # Ensure syllable panel starts at the same position
        self.syllable_panel.sync_syllable_scroll(0)
        
        # Force initial font synchronization
        QTimer.singleShot(100, self.sync_fonts)
        QTimer.singleShot(500, self.sync_fonts)  # Also sync after a longer delay to ensure it happens
    
    def create_lyrics_panel(self):
        """Create the main lyrics editing panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Controls
        controls_layout = QHBoxLayout()
        
        # Color mode toggle
        self.color_mode_checkbox = QCheckBox("Color by Rhymes")
        self.color_mode_checkbox.toggled.connect(self.on_color_mode_changed)
        controls_layout.addWidget(self.color_mode_checkbox)
        
        # Play button
        self.play_button = QPushButton("▶ Play")
        self.play_button.clicked.connect(self.play_current_selection)
        controls_layout.addWidget(self.play_button)
        
        # Time window controls
        controls_layout.addWidget(QLabel("Time Window:"))
        self.time_window_slider = QSlider(Qt.Horizontal)
        self.time_window_slider.setMinimum(1)
        self.time_window_slider.setMaximum(10)
        self.time_window_slider.setValue(2)
        self.time_window_slider.setTickPosition(QSlider.TicksBelow)
        self.time_window_slider.setTickInterval(1)
        self.time_window_slider.valueChanged.connect(self.on_time_window_changed)
        controls_layout.addWidget(self.time_window_slider)
        
        self.time_window_label = QLabel("2.0s")
        self.time_window_label.setMinimumWidth(40)
        controls_layout.addWidget(self.time_window_label)
        
        # Font controls
        controls_layout.addWidget(QLabel("Font:"))
        self.font_combo = QComboBox()
        self.font_combo.addItems(["Arial", "Helvetica", "Times New Roman", "Courier New", "Verdana", "Georgia", "Palatino"])
        self.font_combo.setCurrentText("Arial")
        self.font_combo.currentTextChanged.connect(self.on_font_changed)
        controls_layout.addWidget(self.font_combo)
        
        controls_layout.addWidget(QLabel("Size:"))
        self.font_size_combo = QComboBox()
        self.font_size_combo.addItems(["10", "12", "14", "16", "18", "20", "24", "28", "32"])
        self.font_size_combo.setCurrentText("14")
        self.font_size_combo.currentTextChanged.connect(self.on_font_size_changed)
        controls_layout.addWidget(self.font_size_combo)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Main text editor
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Enter lyrics here...")
        self.text_edit.textChanged.connect(self.on_text_changed)
        self.text_edit.mouseDoubleClickEvent = self.on_double_click
        # Ensure visible and readable text
        try:
            pal = self.text_edit.palette()
            pal.setColor(QPalette.Base, QColor(255, 255, 255))
            pal.setColor(QPalette.Text, QColor(0, 0, 0))
            self.text_edit.setPalette(pal)
        except Exception:
            pass
        self.text_edit.setVisible(True)
        # Ensure the editor expands and has a reasonable minimum size
        try:
            self.text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        except Exception:
            pass
        self.text_edit.setMinimumSize(300, 200)
        # Connect resize event to handle auto-wrapping
        self.text_edit.resizeEvent = self.on_text_edit_resize
        # Set word wrap mode to ensure line breaks are respected
        self.text_edit.setWordWrapMode(QTextOption.NoWrap)
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 8px;
                font-family: Arial;
                font-size: 14px;
                line-height: 1.4;
                white-space: pre-wrap;
            }
        """)
        layout.addWidget(self.text_edit)
        
        return panel
    
    def on_time_window_changed(self, value: int):
        """Handle time window slider change"""
        self.time_window = float(value)
        self.time_window_label.setText(f"{self.time_window:.1f}s")
    
    def on_font_changed(self, font_name: str):
        """Handle font change"""
        current_font = self.text_edit.font()
        current_font.setFamily(font_name)
        self.text_edit.setFont(current_font)
        # Sync font with syllable panel for perfect alignment
        self.syllable_panel.counts_text.setFont(current_font)
        # Update stylesheet to match
        font_size = max(8, current_font.pointSize())  # Minimum 8pt font
        self.syllable_panel.counts_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                font-family: {font_name};
                font-size: {font_size}pt;
                line-height: 1.4;
                padding: 8px;
            }}
        """)
    
    def on_font_size_changed(self, size_text: str):
        """Handle font size change"""
        try:
            size = int(size_text)
            current_font = self.text_edit.font()
            current_font.setPointSize(size)
            self.text_edit.setFont(current_font)
            # Sync font with syllable panel for perfect alignment
            self.syllable_panel.counts_text.setFont(current_font)
            # Update stylesheet to match - use exact same font size as main editor
            font_size = size  # Use exact same size as main editor
            self.syllable_panel.counts_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: #f8f9fa;
                    border: 1px solid #dee2e6;
                    border-radius: 4px;
                    font-family: {current_font.family()};
                    font-size: {font_size}px;
                    font-weight: normal;
                    line-height: 1.4;
                    padding: 8px;
                }}
            """)
        except ValueError:
            pass
    
    def on_color_mode_changed(self, checked: bool):
        """Handle color mode toggle"""
        self.color_mode = "rhyme" if checked else "confidence"
        self.apply_coloring()
    
    def on_double_click(self, event):
        """Handle double-click to play audio"""
        cursor = self.text_edit.cursorForPosition(event.pos())
        cursor.select(QTextCursor.WordUnderCursor)
        word = cursor.selectedText()
        
        # Clean the word (remove chord annotations)
        clean_word = re.sub(r'\[.*?\]', '', word).strip()
        
        if not clean_word or not self.audio_path:
            return
        
        # Find the word in lyrics data and play audio
        for word_data in self.lyrics_data:
            if word_data.text.lower() == clean_word.lower():
                start_time = word_data.start
                end_time = word_data.end
                
                # Calculate time window around the word
                word_duration = end_time - start_time
                window_start = max(0, start_time - self.time_window)
                window_end = end_time + self.time_window
                duration = window_end - window_start
                
                print(f"Playing audio for word '{clean_word}' at {start_time:.2f}s with {duration:.2f}s window")
                self.play_audio_requested.emit(window_start, duration)
                
                # Also start local playback thread
                if self.playback_thread and self.playback_thread.isRunning():
                    self.playback_thread.terminate()
                    self.playback_thread.wait()
                
                self.playback_thread = AudioPlaybackThread(self.audio_path, window_start, duration)
                self.playback_thread.start()
                break
        
        # Also update rhyme panel
        self.update_rhyme_panel(clean_word)
        
        # Call parent's double-click handler
        super().mouseDoubleClickEvent(event)
    
    def update_rhyme_panel(self, word: str):
        """Update the rhyme panel with suggestions for the selected word"""
        text = self.text_edit.toPlainText()
        # Remove chord annotations for word analysis
        clean_text = text
        while '[' in clean_text and ']' in clean_text:
            start = clean_text.find('[')
            end = clean_text.find(']', start)
            if end == -1:
                break
            clean_text = clean_text[:start] + clean_text[end+1:]
        
        all_words = re.findall(r'\b\w+\b', clean_text.lower())
        self.rhyme_panel.update_rhymes(word, all_words)
    
    def play_current_selection(self):
        """Play audio for the currently selected text"""
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            # Find the corresponding audio segment
            for word_data in self.lyrics_data:
                if word_data.text in selected_text:
                    start_time = word_data.start
                    end_time = word_data.end
                    duration = end_time - start_time
                    self.play_audio_requested.emit(start_time, duration)
                    break
    
    def on_text_scroll(self, value: int):
        """Handle text editor scroll to sync with syllable panel"""
        self.syllable_panel.sync_syllable_scroll(value)
    
    def on_text_edit_resize(self, event):
        """Handle text editor resize for auto-wrapping"""
        # Call parent's resize event first
        super().resizeEvent(event)
        
        # Trigger auto-wrapping after resize
        QTimer.singleShot(50, self.apply_auto_wrapping)
    
    def set_audio_path(self, audio_path: str):
        """Set the audio file path for playback"""
        self.audio_path = audio_path
        print(f"Enhanced lyrics editor audio path set to: {audio_path}")
    
    def set_lyrics_data(self, lyrics_data: List[WordRow]):
        """Set lyrics data and update display"""
        self.lyrics_data = lyrics_data
        
        # Convert to text format with chords (CCLI style)
        text_lines = []
        current_line = []
        
        for word in lyrics_data:
            # Add chord if available (place before word for better readability)
            word_text = word.text
            if word.chord:
                word_text = f"[{word.chord}]{word_text}"
            
            current_line.append(word_text)
            
            # Check for line break (either from punctuation or stored line_break flag)
            should_break = (word.text.endswith(('.', '!', '?', ':', ';')) or 
                           getattr(word, 'line_break', False))
            
            if should_break:
                text_lines.append(' '.join(current_line))
                current_line = []
        
        # Add any remaining words
        if current_line:
            text_lines.append(' '.join(current_line))
        
        # Set text in editor (prevent recursion)
        self._updating_text = True
        final_text = '\n'.join(text_lines)
        self.text_edit.setPlainText(final_text)
        self._updating_text = False
        
        # Update syllable counts
        self.syllable_panel.update_counts('\n'.join(text_lines))
        # Ensure syllable panel scrolls to top initially
        self.syllable_panel.sync_syllable_scroll(0)
        
        # Sync font with main editor for perfect alignment
        main_font = self.text_edit.font()
        self.syllable_panel.counts_text.setFont(main_font)
        # Also sync the font size specifically (use exact same size as main editor)
        font_size = main_font.pointSize()  # Use exact same size as main editor
        if font_size <= 0:  # Handle case where font size might be invalid
            font_size = 14  # Default to 14 if invalid
        self.syllable_panel.counts_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                font-family: {main_font.family()};
                font-size: {font_size}px;
                font-weight: normal;
                line-height: 1.4;
                padding: 8px;
            }}
        """)
        
        # Apply auto-wrapping after setting text (with a small delay)
        QTimer.singleShot(100, self.apply_auto_wrapping)
        
        # Also trigger auto-wrapping when the editor is resized
        self.text_edit.resizeEvent = self.on_text_edit_resize
        
        # Force auto-wrapping immediately to ensure it happens
        QTimer.singleShot(200, self.apply_auto_wrapping)
        
        # Analyze rhymes for coloring (debounced)
        self._debounce_timer.start(10)
        
        # Apply initial coloring
        self._analyze_and_color()
    
    def set_song_data(self, song_data):
        """Set song data and populate lyrics editor"""
        if hasattr(song_data, 'words') and song_data.words:
            # Convert song data words to WordRow format
            lyrics_data = []
            for word in song_data.words:
                if hasattr(word, 'to_dict'):
                    word_dict = word.to_dict()
                else:
                    word_dict = word
                
                word_row = WordRow(
                    text=word_dict.get('text', ''),
                    start=word_dict.get('start', 0.0),
                    end=word_dict.get('end', 0.0),
                    confidence=word_dict.get('confidence', 0.0),
                    chord=word_dict.get('chord'),
                    line_break=word_dict.get('line_break', False)
                )
                lyrics_data.append(word_row)
            
            print(f"Setting {len(lyrics_data)} words in enhanced lyrics editor")
            self.set_lyrics_data(lyrics_data)
    
    def on_text_changed(self):
        """Handle text changes"""
        # Prevent recursion when programmatically updating text
        if self._updating_text:
            return
            
        text = self.text_edit.toPlainText()
        self.lyrics_changed.emit(text)
        
        # Update syllable counts based on current displayed text
        self.syllable_panel.update_counts(text)
        
        # Debounce rhyme analysis
        self._debounce_timer.start(250)
    
    def apply_auto_wrapping(self):
        """Apply automatic text wrapping based on available editor width"""
        if not self.lyrics_data:
            return
        
        # Get current text and document
        text = self.text_edit.toPlainText()
        
        # Don't apply auto-wrapping if there's no text yet
        if not text.strip():
            return
        
        # Get the width of the text editor (minus margins)
        editor_width = self.text_edit.viewport().width() - 40  # Account for margins
        
        # Don't apply if editor width is too small
        if editor_width < 200:
            return
        
        # Use a more aggressive approach: force wrapping at a reasonable character limit
        # This ensures the text is actually wrapped and visible
        max_chars_per_line = 60  # Force wrapping at 60 characters for better readability
        
        print(f"Auto-wrapping: editor width={editor_width}, max chars per line={max_chars_per_line}")
        
        # Process each line to check for wrapping
        lines = text.split('\n')
        new_lines = []
        
        for line in lines:
            if not line.strip():
                new_lines.append(line)
                continue
            
            # Check if this line needs wrapping
            if len(line) <= max_chars_per_line:
                new_lines.append(line)
                continue
            
            # Split long lines at word boundaries
            words = line.split()
            current_line = []
            current_length = 0
            
            for word in words:
                word_length = len(word)
                space_length = 1 if current_line else 0  # Add space only if not first word
                
                # Check if adding this word would exceed the limit
                if current_line and (current_length + word_length + space_length > max_chars_per_line):
                    # This word would cause wrapping, insert line break before it
                    new_lines.append(' '.join(current_line))
                    current_line = [word]
                    current_length = word_length
                else:
                    current_line.append(word)
                    current_length += word_length + space_length
            
            # Add the last line
            if current_line:
                new_lines.append(' '.join(current_line))
        
        # Update the text if changes were made
        new_text = '\n'.join(new_lines)
        print(f"Original text has {len(text.split(chr(10)))} lines, new text has {len(new_text.split(chr(10)))} lines")
        
        if new_text != text:
            print(f"Auto-wrapping applied: {len(text.split())} words, {len(new_text.split(chr(10)))} lines")
            print(f"First few lines of new text: {new_text[:200]}...")
            
            # Prevent recursion
            self._updating_text = True
            # Clear the text first
            self.text_edit.clear()
            # Ensure line breaks are properly set
            self.text_edit.setPlainText(new_text)
            # Force a repaint to ensure the text is displayed correctly
            self.text_edit.repaint()
            # Force an update
            self.text_edit.update()
            self._updating_text = False
            
            # Update the lyrics data with line break information
            self.update_lyrics_data_with_line_breaks(new_text)
            
            # Update syllable counts based on the wrapped text
            self.syllable_panel.update_counts(new_text)
        else:
            print("No auto-wrapping needed")
    
    def update_lyrics_data_with_line_breaks(self, text: str):
        """Update lyrics data to include line break information"""
        lines = text.split('\n')
        word_index = 0
        
        for line in lines:
            words_in_line = line.split()
            for i, word in enumerate(words_in_line):
                if word_index < len(self.lyrics_data):
                    # Check if this word should have a line break after it
                    is_last_word_in_line = (i == len(words_in_line) - 1)
                    self.lyrics_data[word_index].line_break = is_last_word_in_line
                word_index += 1
        
        # Emit the updated lyrics data so it can be saved with newlines
        self.lyrics_changed.emit(text)
    
    def _analyze_and_color(self):
        """Analyze text and apply coloring"""
        self.analyze_rhymes()
        self._reset_formatting()
        self.apply_coloring()
    
    def apply_coloring(self):
        """Apply color coding based on current mode"""
        if self.color_mode == "confidence":
            # Apply confidence coloring first, then rhyme coloring on top
            self.apply_confidence_coloring()
            self.apply_rhyme_coloring()
        else:
            # Apply rhyme coloring first, then confidence coloring on top
            self.apply_rhyme_coloring()
            self.apply_confidence_coloring()
    
    def apply_rhyme_coloring(self):
        """Apply rhyme-based color coding. Perfect groups are bold; near groups not bold."""
        colors = [
            QColor(255, 0, 0), QColor(0, 128, 0), QColor(0, 0, 200), QColor(200, 120, 0),
            QColor(128, 0, 128), QColor(200, 0, 100), QColor(0, 160, 160), QColor(160, 160, 0),
        ]
        doc = self.text_edit.document()

        # First, set all words to black (default for non-rhyming words)
        black_fmt = QTextCharFormat()
        black_fmt.setForeground(QColor(0, 0, 0))
        black_fmt.setFontWeight(QFont.Normal)
        
        # Get all words from the text
        text = self.text_edit.toPlainText()
        all_words = []
        for line in text.split('\n'):
            for word in line.split():
                # Clean word of punctuation and brackets, but preserve apostrophes
                # Handle contractions like "don't", "can't", "I'll" as single words
                clean_word = ''
                for c in word:
                    if c.isalpha() or c == "'":
                        clean_word += c
                if clean_word:
                    all_words.append(clean_word.lower())
        
        # Also handle chord annotations by extracting words from them
        # Look for patterns like [C]word or word[C] and extract the word part
        chord_pattern = r'\[([^\]]+)\]([a-zA-Z\']+)|([a-zA-Z\']+)\[([^\]]+)\]'
        import re
        matches = re.findall(chord_pattern, text)
        for match in matches:
            if match[1]:  # [C]word pattern
                clean_word = ''.join(c for c in match[1] if c.isalpha() or c == "'")
                if clean_word:
                    all_words.append(clean_word.lower())
            if match[2]:  # word[C] pattern
                clean_word = ''.join(c for c in match[2] if c.isalpha() or c == "'")
                if clean_word:
                    all_words.append(clean_word.lower())
        
        # Set all words to black first
        for word in set(all_words):
            # Use word boundaries to avoid partial matches
            cursor = doc.find(word, 0, QTextDocument.FindWholeWords)
            while not cursor.isNull():
                cursor.mergeCharFormat(black_fmt)
                cursor = doc.find(word, cursor, QTextDocument.FindWholeWords)

        # Apply perfect rhyme groups (bold)
        group_to_words = {}
        for w, g in self.rhyme_groups.items():
            group_to_words.setdefault(g, []).append(w)

        for i, (group_name, words) in enumerate(group_to_words.items()):
            color = colors[i % len(colors)]
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            fmt.setFontWeight(QFont.Bold)
            for w in words:
                # Search for the word in the text and apply formatting
                # Handle apostrophes by searching for the clean version
                clean_word = ''.join(c for c in w if c.isalpha() or c == "'")
                cursor = doc.find(clean_word, 0, QTextDocument.FindWholeWords)
                while not cursor.isNull():
                    cursor.mergeCharFormat(fmt)
                    cursor = doc.find(clean_word, cursor, QTextDocument.FindWholeWords)

        # Apply near rhyme groups (same palette, not bold)
        near_group_to_words = {}
        for w, g in self.near_rhyme_groups.items():
            near_group_to_words.setdefault(g, []).append(w)

        for i, (group_name, words) in enumerate(near_group_to_words.items()):
            color = colors[i % len(colors)]
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            fmt.setFontWeight(QFont.Normal)
            for w in words:
                # Search for the word in the text and apply formatting
                # Handle apostrophes by searching for the clean version
                clean_word = ''.join(c for c in w if c.isalpha() or c == "'")
                cursor = doc.find(clean_word, 0, QTextDocument.FindWholeWords)
                while not cursor.isNull():
                    cursor.mergeCharFormat(fmt)
                    cursor = doc.find(clean_word, cursor, QTextDocument.FindWholeWords)
    
    def apply_confidence_coloring(self):
        """Apply confidence-based color coding to all words"""
        doc = self.text_edit.document()
        
        if not self.lyrics_data:
            return
            
        for word_data in self.lyrics_data:
            # Calculate color based on confidence
            confidence = word_data.confidence
            red = int(255 * (1.0 - confidence))
            green = int(255 * confidence)
            color = QColor(red, green, 0)
            
            # Create format - preserve existing formatting (like bold for rhymes)
            format = QTextCharFormat()
            format.setForeground(color)
            
            # Find and format the word (search for the word text only, not with chord)
            word_text = word_data.text
            
            # Handle words with apostrophes by searching for the clean version
            clean_word = ''.join(c for c in word_text if c.isalpha() or c == "'")
            
            # Search for the word in the text
            cursor = doc.find(clean_word, 0, QTextDocument.FindWholeWords)
            
            while not cursor.isNull():
                # Get current format and merge with confidence color
                current_format = cursor.charFormat()
                merged_format = QTextCharFormat()
                merged_format.setForeground(color)
                # Preserve font weight (bold for perfect rhymes)
                merged_format.setFontWeight(current_format.fontWeight())
                cursor.mergeCharFormat(merged_format)
                cursor = doc.find(clean_word, cursor, QTextDocument.FindWholeWords)
    
    def analyze_rhymes(self):
        """Analyze rhyming patterns using pronunciation-based grouping with fallbacks."""
        text = self.text_edit.toPlainText()
        # Remove chord annotations like [C]
        clean_text = text
        while '[' in clean_text and ']' in clean_text:
            start = clean_text.find('[')
            end = clean_text.find(']', start)
            if end == -1:
                break
            clean_text = clean_text[:start] + clean_text[end+1:]

        # Simple word extraction
        words = []
        for word in clean_text.lower().split():
            # Clean word of punctuation and brackets, but preserve apostrophes
            # Handle contractions like "don't", "can't", "I'll" as single words
            cleaned = ''
            for c in word:
                if c.isalpha() or c == "'":
                    cleaned += c
            if cleaned:
                words.append(cleaned)

        unique_words = list(dict.fromkeys(words))
        
        # Initialize groups
        self.rhyme_groups = {}
        self.near_rhyme_groups = {}
        
        # Use proper rhyme analysis - no arbitrary grouping
        remaining_words = unique_words
        
        # Build perfect rhyme groups by rhyme_key for remaining words
        key_to_words = {}
        for w in remaining_words:
            if w in self._rhyme_key_cache:
                key = self._rhyme_key_cache[w]
            else:
                key = self.rhyme_analyzer.rhyme_key(w)
                self._rhyme_key_cache[w] = key
            if not key:
                continue
            key_to_words.setdefault(key, []).append(w)

        group_id = 0  # Start from 0 since we removed manual groups
        for key, group_words in key_to_words.items():
            if len(group_words) < 2:
                continue
            group_id += 1
            group_name = f"group_{group_id}"
            for w in group_words:
                self.rhyme_groups[w] = group_name

        # Near rhyme groups by near_rhyme_key for remaining words
        near_key_to_words = {}
        for w in remaining_words:
            if w in self.rhyme_groups:  # Skip words already in perfect rhyme groups
                continue
            if w in self._near_key_cache:
                nkey = self._near_key_cache[w]
            else:
                try:
                    nkey = self.rhyme_analyzer.near_rhyme_key(w)
                    self._near_key_cache[w] = nkey
                except AttributeError as e:
                    print(f"Error: {e}")
                    print(f"rhyme_analyzer type: {type(self.rhyme_analyzer)}")
                    print(f"rhyme_analyzer dir: {dir(self.rhyme_analyzer)}")
                    nkey = ""
                    self._near_key_cache[w] = nkey
            if not nkey:
                continue
            near_key_to_words.setdefault(nkey, []).append(w)

        near_id = 0  # Start from 0 since we removed manual groups
        for nkey, group_words in near_key_to_words.items():
            if len(group_words) < 2:
                continue
            near_id += 1
            group_name = f"near_{near_id}"
            for w in group_words:
                self.near_rhyme_groups[w] = group_name
    
    def _reset_formatting(self):
        """Reset all text formatting to default before applying new coloring."""
        cursor = self.text_edit.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        default_format = QTextCharFormat()
        cursor.setCharFormat(default_format)
        cursor.clearSelection()
        cursor.endEditBlock()
    
    def get_lyrics_text(self):
        """Get the current lyrics text"""
        return self.text_edit.toPlainText()
    
    def sync_fonts(self):
        """Synchronize font sizes between main editor and syllable panel"""
        try:
            main_font = self.text_edit.font()
            self.syllable_panel.counts_text.setFont(main_font)
            font_size = main_font.pointSize()
            if font_size <= 0:  # Handle case where font size might be invalid
                font_size = 14  # Default to 14 if invalid
            self.syllable_panel.counts_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: #f8f9fa;
                    border: 1px solid #dee2e6;
                    border-radius: 4px;
                    font-family: {main_font.family()};
                    font-size: {font_size}px;
                    font-weight: normal;
                    line-height: 1.4;
                    padding: 8px;
                }}
            """)
        except Exception as e:
            print(f"Font sync error: {e}")
    
    def set_lyrics_text(self, text: str):
        """Set the lyrics text"""
        self._updating_text = True
        self.text_edit.setPlainText(text)
        self._updating_text = False
