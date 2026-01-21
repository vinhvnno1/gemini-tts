/**
 * Voice AI Client - Real-time audio streaming with Gemini 2.0 Flash
 */

class VoiceAI {
    constructor() {
        // Audio settings
        this.inputSampleRate = 16000;
        this.outputSampleRate = 24000;
        this.bufferSize = 4096;

        // State
        this.isListening = false;
        this.isConnected = false;
        this.ws = null;
        this.audioContext = null;
        this.mediaStream = null;
        this.scriptProcessor = null;

        // Audio playback queue (jitter buffer)
        this.audioQueue = [];
        this.isPlaying = false;

        // DOM elements
        this.micButton = document.getElementById('micButton');
        this.micHint = document.getElementById('micHint');
        this.statusBadge = document.getElementById('statusBadge');
        this.statusText = this.statusBadge.querySelector('.status-text');
        this.responseContainer = document.getElementById('responseContainer');
        this.responseText = document.getElementById('responseText');
        this.visualizer = document.getElementById('visualizer');
        this.visualizerContainer = this.visualizer.parentElement;

        // Visualizer
        this.canvasCtx = this.visualizer.getContext('2d');
        this.analyser = null;
        this.animationId = null;

        this.init();
    }

    init() {
        // Setup event listeners
        this.micButton.addEventListener('click', () => this.toggleMic());

        // Resize canvas
        this.resizeCanvas();
        window.addEventListener('resize', () => this.resizeCanvas());

        // Connect to server
        this.connect();
    }

    resizeCanvas() {
        const rect = this.visualizer.getBoundingClientRect();
        this.visualizer.width = rect.width * window.devicePixelRatio;
        this.visualizer.height = rect.height * window.devicePixelRatio;
        this.canvasCtx.scale(window.devicePixelRatio, window.devicePixelRatio);
    }

    updateStatus(status, text) {
        this.statusBadge.className = 'status-badge ' + status;
        this.statusText.textContent = text;
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        this.updateStatus('', 'Connecting...');

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
        };

        this.ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            this.handleMessage(message);
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.updateStatus('error', 'Connection error');
        };

        this.ws.onclose = () => {
            console.log('WebSocket closed');
            this.isConnected = false;
            this.updateStatus('error', 'Disconnected');

            // Reconnect after delay
            setTimeout(() => this.connect(), 3000);
        };
    }

    handleMessage(message) {
        switch (message.type) {
            case 'connected':
                this.isConnected = true;
                this.updateStatus('connected', 'Ready');
                break;

            case 'audio':
                // Queue audio for playback
                this.queueAudio(message.data);
                break;

            case 'text':
                // Display streaming text
                this.showResponse(message.data);
                break;

            case 'turnComplete':
                // AI finished speaking
                if (!this.isListening) {
                    this.updateStatus('connected', 'Ready');
                }
                break;

            case 'interrupted':
                // Clear audio queue on interruption
                this.audioQueue = [];
                break;

            case 'error':
                console.error('Server error:', message.message);
                this.updateStatus('error', 'Error');
                break;
        }
    }

    async toggleMic() {
        if (this.isListening) {
            this.stopListening();
        } else {
            await this.startListening();
        }
    }

    async startListening() {
        try {
            // Request microphone access
            this.mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: this.inputSampleRate,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                }
            });

            // Create audio context
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: this.inputSampleRate
            });

            // Create source and processor
            const source = this.audioContext.createMediaStreamSource(this.mediaStream);
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 256;

            // Use ScriptProcessor for raw PCM access
            this.scriptProcessor = this.audioContext.createScriptProcessor(this.bufferSize, 1, 1);

            source.connect(this.analyser);
            this.analyser.connect(this.scriptProcessor);
            this.scriptProcessor.connect(this.audioContext.destination);

            // Process audio
            this.scriptProcessor.onaudioprocess = (event) => {
                if (!this.isListening || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;

                const inputData = event.inputBuffer.getChannelData(0);

                // Convert to 16-bit PCM
                const pcmData = this.float32ToPCM16(inputData);

                // Convert to base64
                const base64Data = this.arrayBufferToBase64(pcmData.buffer);

                // Send to server
                this.ws.send(JSON.stringify({
                    type: 'audio',
                    data: base64Data
                }));
            };

            this.isListening = true;
            this.micButton.classList.add('active');
            this.micHint.textContent = 'Click to stop';
            this.visualizerContainer.classList.add('active');
            this.updateStatus('listening', 'Listening...');

            // Start visualizer
            this.startVisualizer();

        } catch (error) {
            console.error('Microphone error:', error);
            this.updateStatus('error', 'Mic access denied');
        }
    }

    stopListening() {
        this.isListening = false;

        // Stop audio processing
        if (this.scriptProcessor) {
            this.scriptProcessor.disconnect();
            this.scriptProcessor = null;
        }

        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(track => track.stop());
            this.mediaStream = null;
        }

        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }

        this.micButton.classList.remove('active');
        this.micHint.textContent = 'Click to start speaking';
        this.visualizerContainer.classList.remove('active');
        this.updateStatus('connected', 'Ready');

        // Stop visualizer
        this.stopVisualizer();
    }

    float32ToPCM16(float32Array) {
        const pcm16 = new Int16Array(float32Array.length);
        for (let i = 0; i < float32Array.length; i++) {
            const s = Math.max(-1, Math.min(1, float32Array[i]));
            pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        return pcm16;
    }

    arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }

    base64ToArrayBuffer(base64) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }

    pcm16ToFloat32(pcm16Buffer) {
        const pcm16 = new Int16Array(pcm16Buffer);
        const float32 = new Float32Array(pcm16.length);
        for (let i = 0; i < pcm16.length; i++) {
            float32[i] = pcm16[i] / (pcm16[i] < 0 ? 0x8000 : 0x7FFF);
        }
        return float32;
    }

    queueAudio(base64Data) {
        const buffer = this.base64ToArrayBuffer(base64Data);
        const float32 = this.pcm16ToFloat32(buffer);
        this.audioQueue.push(float32);

        this.updateStatus('speaking', 'Speaking...');

        if (!this.isPlaying) {
            this.playNextAudio();
        }
    }

    async playNextAudio() {
        if (this.audioQueue.length === 0) {
            this.isPlaying = false;
            if (this.isListening) {
                this.updateStatus('listening', 'Listening...');
            } else {
                this.updateStatus('connected', 'Ready');
            }
            return;
        }

        this.isPlaying = true;

        // Create playback context if needed
        if (!this.playbackContext) {
            this.playbackContext = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: this.outputSampleRate
            });
        }

        const float32Data = this.audioQueue.shift();

        // Create audio buffer
        const audioBuffer = this.playbackContext.createBuffer(1, float32Data.length, this.outputSampleRate);
        audioBuffer.copyToChannel(float32Data, 0);

        // Create source and play
        const source = this.playbackContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(this.playbackContext.destination);

        source.onended = () => {
            this.playNextAudio();
        };

        source.start();
    }

    showResponse(text) {
        this.responseContainer.classList.add('visible');
        this.responseText.textContent += text;

        // Clear after some time
        clearTimeout(this.responseTimeout);
        this.responseTimeout = setTimeout(() => {
            this.responseText.textContent = '';
            this.responseContainer.classList.remove('visible');
        }, 10000);
    }

    startVisualizer() {
        const draw = () => {
            if (!this.analyser) return;

            this.animationId = requestAnimationFrame(draw);

            const bufferLength = this.analyser.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);
            this.analyser.getByteFrequencyData(dataArray);

            const width = this.visualizer.width / window.devicePixelRatio;
            const height = this.visualizer.height / window.devicePixelRatio;

            // Clear canvas
            this.canvasCtx.clearRect(0, 0, width, height);

            // Draw bars
            const barWidth = (width / bufferLength) * 2.5;
            let x = 0;

            for (let i = 0; i < bufferLength; i++) {
                const barHeight = (dataArray[i] / 255) * height * 0.8;

                // Gradient color
                const gradient = this.canvasCtx.createLinearGradient(0, height, 0, height - barHeight);
                gradient.addColorStop(0, 'rgba(99, 102, 241, 0.8)');
                gradient.addColorStop(1, 'rgba(139, 92, 246, 0.8)');

                this.canvasCtx.fillStyle = gradient;
                this.canvasCtx.fillRect(x, height - barHeight, barWidth - 2, barHeight);

                x += barWidth;
            }
        };

        draw();
    }

    stopVisualizer() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }

        // Clear canvas
        const width = this.visualizer.width / window.devicePixelRatio;
        const height = this.visualizer.height / window.devicePixelRatio;
        this.canvasCtx.clearRect(0, 0, width, height);
    }
}

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    window.voiceAI = new VoiceAI();
});
