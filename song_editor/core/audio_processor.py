#!/usr/bin/env python3
"""
Audio Processor Module

Handles audio loading, denoising, normalization, and source separation.
"""

import os
import logging
import numpy as np
import librosa
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import psutil
import time

try:
    import torch
    import torchaudio
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    from demucs.api import Separator
    DEMUCS_AVAILABLE = True
except ImportError:
    DEMUCS_AVAILABLE = False

try:
    import noisereduce as nr
    NOISEREDUCE_AVAILABLE = True
except ImportError:
    NOISEREDUCE_AVAILABLE = False

try:
    import pyloudnorm as pyln
    PYLN_AVAILABLE = True
except ImportError:
    PYLN_AVAILABLE = False


class AudioProcessor:
    """Handles audio processing pipeline."""
    
    def __init__(
        self,
        use_demucs: bool = True,
        save_intermediate: bool = True,
        target_sr: int = 44100,
        denoise_strength: float = 0.5,
        normalize_lufs: float = -23.0
    ):
        self.use_demucs = use_demucs and DEMUCS_AVAILABLE
        self.save_intermediate = save_intermediate
        self.target_sr = target_sr
        self.denoise_strength = denoise_strength
        self.normalize_lufs = normalize_lufs
        
        self.separator = None
        self.audio_data = None
        self.processing_info = {}
        
        if self.use_demucs:
            self._initialize_demucs()
    
    def _initialize_demucs(self):
        """Initialize Demucs separator."""
        try:
            if DEMUCS_AVAILABLE:
                self.separator = Separator('htdemucs')
                logging.info("Demucs initialized successfully")
            else:
                logging.warning("Demucs not available, using fallback methods")
        except Exception as e:
            logging.error(f"Failed to initialize Demucs: {e}")
            self.use_demucs = False
    
    def _log_memory_usage(self, stage: str):
        """Log memory usage for a processing stage."""
        process = psutil.Process()
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024
        
        self.processing_info[f"{stage}_memory_mb"] = memory_mb
        logging.debug(f"{stage} memory usage: {memory_mb:.1f} MB")
    
    def _calculate_audio_levels(self, audio: np.ndarray, sr: int) -> Dict[str, float]:
        """Calculate audio levels and statistics."""
        levels = {}
        
        # RMS levels
        levels['rms'] = float(np.sqrt(np.mean(audio**2)))
        levels['rms_db'] = float(20 * np.log10(levels['rms'] + 1e-10))
        
        # Peak levels
        levels['peak'] = float(np.max(np.abs(audio)))
        levels['peak_db'] = float(20 * np.log10(levels['peak'] + 1e-10))
        
        # Dynamic range
        levels['dynamic_range_db'] = levels['peak_db'] - levels['rms_db']
        
        # Crest factor
        levels['crest_factor'] = float(levels['peak'] / (levels['rms'] + 1e-10))
        
        return levels
    
    def _detect_tempo(self, audio: np.ndarray, sr: int) -> Optional[float]:
        """Detect tempo using librosa."""
        try:
            tempo, _ = librosa.beat.beat_track(y=audio, sr=sr)
            return float(tempo)
        except Exception as e:
            logging.warning(f"Tempo detection failed: {e}")
            return None
    
    def _detect_key(self, audio: np.ndarray, sr: int) -> Optional[Dict[str, Any]]:
        """Detect musical key using librosa."""
        try:
            # Extract chromagram
            chromagram = librosa.feature.chroma_cqt(y=audio, sr=sr)
            
            # Get key profile
            key_profile = np.mean(chromagram, axis=1)
            
            # Find dominant key
            key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            dominant_key_idx = np.argmax(key_profile)
            dominant_key = key_names[dominant_key_idx]
            
            # Determine major/minor
            # This is a simplified approach - in practice you'd use more sophisticated methods
            major_scale = [0, 2, 4, 5, 7, 9, 11]
            minor_scale = [0, 2, 3, 5, 7, 8, 10]
            
            major_score = sum(key_profile[(dominant_key_idx + note) % 12] for note in major_scale)
            minor_score = sum(key_profile[(dominant_key_idx + note) % 12] for note in minor_scale)
            
            mode = "major" if major_score > minor_score else "minor"
            
            return {
                'key': dominant_key,
                'mode': mode,
                'confidence': float(max(major_score, minor_score) / sum(key_profile))
            }
            
        except Exception as e:
            logging.warning(f"Key detection failed: {e}")
            return None
    
    def load_audio(self, file_path: str) -> Tuple[np.ndarray, int]:
        """Load audio file."""
        try:
            logging.info(f"Loading audio: {file_path}")
            start_time = time.time()
            
            # Load audio
            audio, sr = librosa.load(file_path, sr=self.target_sr, mono=True)
            
            # Store original info
            self.audio_data = {
                'original_path': file_path,
                'original_sr': sr,
                'duration': len(audio) / sr,
                'channels': 1
            }
            
            load_time = time.time() - start_time
            self.processing_info['load_time'] = load_time
            self._log_memory_usage('load')
            
            logging.info(f"Audio loaded: {len(audio)} samples, {sr} Hz, {self.audio_data['duration']:.2f}s")
            return audio, sr
            
        except Exception as e:
            logging.error(f"Failed to load audio: {e}")
            raise
    
    def denoise_audio(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """Denoise audio using noisereduce."""
        if not NOISEREDUCE_AVAILABLE:
            logging.warning("Noisereduce not available, skipping denoising")
            return audio
        
        try:
            logging.info("Denoising audio...")
            start_time = time.time()
            
            # Apply noise reduction
            denoised = nr.reduce_noise(
                y=audio, 
                sr=sr, 
                stationary=True,
                prop_decrease=self.denoise_strength
            )
            
            denoise_time = time.time() - start_time
            self.processing_info['denoise_time'] = denoise_time
            self._log_memory_usage('denoise')
            
            logging.info(f"Denoising completed in {denoise_time:.2f}s")
            return denoised
            
        except Exception as e:
            logging.error(f"Denoising failed: {e}")
            return audio
    
    def normalize_audio(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """Normalize audio to target LUFS."""
        if not PYLN_AVAILABLE:
            logging.warning("Pyloudnorm not available, using RMS normalization")
            # Fallback to RMS normalization
            rms = np.sqrt(np.mean(audio**2))
            target_rms = 0.1
            normalized = audio * (target_rms / (rms + 1e-10))
            return normalized
        
        try:
            logging.info("Normalizing audio...")
            start_time = time.time()
            
            # Create loudness meter
            meter = pyln.Meter(sr)
            
            # Measure current loudness
            current_lufs = meter.integrated_loudness(audio)
            
            # Calculate gain needed
            gain_db = self.normalize_lufs - current_lufs
            gain_linear = 10**(gain_db / 20)
            
            # Apply normalization
            normalized = audio * gain_linear
            
            # Ensure no clipping
            max_val = np.max(np.abs(normalized))
            if max_val > 0.95:
                normalized = normalized * (0.95 / max_val)
            
            normalize_time = time.time() - start_time
            self.processing_info['normalize_time'] = normalize_time
            self._log_memory_usage('normalize')
            
            logging.info(f"Normalization completed: {current_lufs:.1f} LUFS -> {self.normalize_lufs:.1f} LUFS")
            return normalized
            
        except Exception as e:
            logging.error(f"Normalization failed: {e}")
            return audio
    
    def separate_sources(self, audio: np.ndarray, sr: int) -> Dict[str, np.ndarray]:
        """Separate audio sources using Demucs or fallback."""
        if self.use_demucs and self.separator:
            try:
                logging.info("Separating audio sources with Demucs...")
                start_time = time.time()
                
                # Save temporary audio for Demucs
                temp_path = self._save_audio_temp(audio, sr)
                
                # Separate sources
                sources = self.separator.separate_file(temp_path)
                
                # Clean up temp file
                os.remove(temp_path)
                
                # Convert to numpy arrays
                separated = {}
                for source_name, source_audio in sources.items():
                    if source_audio.dim() == 3:  # [channels, time]
                        separated[source_name] = source_audio[0].numpy()  # Take first channel
                    else:
                        separated[source_name] = source_audio.numpy()
                
                separate_time = time.time() - start_time
                self.processing_info['separate_time'] = separate_time
                self._log_memory_usage('separate')
                
                logging.info(f"Source separation completed in {separate_time:.2f}s")
                return separated
                
            except Exception as e:
                logging.error(f"Demucs separation failed: {e}")
                # Fall back to no separation
                return {'vocals': audio, 'accompaniment': audio}
        else:
            logging.info("Using fallback source separation (no separation)")
            # Simple fallback: assume vocals are in center frequencies
            # This is a very basic approach
            return {'vocals': audio, 'accompaniment': audio}
    
    def _save_audio_temp(self, audio: np.ndarray, sr: int) -> str:
        """Save audio to temporary file."""
        import tempfile
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_path = temp_file.name
        temp_file.close()
        
        # Save using librosa
        import soundfile as sf
        sf.write(temp_path, audio, sr)
        
        return temp_path
    
    def _save_intermediate_files(self, audio: np.ndarray, sr: int, stage: str):
        """Save intermediate audio files if requested."""
        if not self.save_intermediate:
            return
        
        try:
            output_dir = Path("intermediate_outputs")
            output_dir.mkdir(exist_ok=True)
            
            output_path = output_dir / f"{stage}_{int(time.time())}.wav"
            
            import soundfile as sf
            sf.write(str(output_path), audio, sr)
            
            logging.info(f"Saved intermediate file: {output_path}")
            
        except Exception as e:
            logging.warning(f"Failed to save intermediate file: {e}")
    
    def process(self, file_path: str) -> Dict[str, Any]:
        """Process audio file through the complete pipeline."""
        try:
            logging.info(f"Starting audio processing: {file_path}")
            total_start_time = time.time()
            
            # Load audio
            audio, sr = self.load_audio(file_path)
            
            # Save intermediate if requested
            if self.save_intermediate:
                self._save_intermediate_files(audio, sr, "01_loaded")
            
            # Denoise
            audio = self.denoise_audio(audio, sr)
            if self.save_intermediate:
                self._save_intermediate_files(audio, sr, "02_denoised")
            
            # Normalize
            audio = self.normalize_audio(audio, sr)
            if self.save_intermediate:
                self._save_intermediate_files(audio, sr, "03_normalized")
            
            # Separate sources
            separated = self.separate_sources(audio, sr)
            vocals = separated.get('vocals', audio)
            accompaniment = separated.get('accompaniment', audio)
            
            if self.save_intermediate:
                self._save_intermediate_files(vocals, sr, "04_vocals")
                self._save_intermediate_files(accompaniment, sr, "05_accompaniment")
            
            # Analyze audio
            analysis = {
                'duration': len(audio) / sr,
                'sample_rate': sr,
                'channels': 1,
                'audio_levels': self._calculate_audio_levels(audio, sr),
                'tempo': self._detect_tempo(audio, sr),
                'key': self._detect_key(audio, sr)
            }
            
            # Calculate total processing time
            total_time = time.time() - total_start_time
            self.processing_info['total_time'] = total_time
            
            logging.info(f"Audio processing completed in {total_time:.2f}s")
            
            return {
                'audio': audio,
                'vocals': vocals,
                'accompaniment': accompaniment,
                'sample_rate': sr,
                'analysis': analysis,
                'processing_info': self.processing_info
            }
            
        except Exception as e:
            logging.error(f"Audio processing failed: {e}")
            raise
    
    def get_timestamp(self) -> str:
        """Get current timestamp string."""
        return time.strftime("%Y%m%d_%H%M%S")
    
    def get_processing_info(self) -> Dict[str, Any]:
        """Get processing information."""
        return self.processing_info.copy()
    
    def cleanup(self):
        """Clean up resources."""
        if self.separator:
            del self.separator
            self.separator = None
        
        if self.audio_data:
            self.audio_data.clear()
        
        self.processing_info.clear()
        
        logging.info("Audio processor cleaned up")
