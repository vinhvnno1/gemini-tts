import express from 'express';
import { createServer } from 'http';
import { WebSocketServer, WebSocket } from 'ws';
import { GoogleGenAI, Modality } from '@google/genai';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const app = express();
const server = createServer(app);
const wss = new WebSocketServer({ server, path: '/ws' });

// Serve static files
app.use(express.static(__dirname));
app.use(express.json());

const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
if (!GEMINI_API_KEY) {
    console.error('ERROR: GEMINI_API_KEY environment variable is required');
    process.exit(1);
}

const ai = new GoogleGenAI({ apiKey: GEMINI_API_KEY });

// Gemini Live API configuration
const MODEL = 'gemini-2.5-flash-preview-native-audio-dialog';
const CONFIG = {
    responseModalities: [Modality.AUDIO],
    systemInstruction: `You are a helpful and friendly AI voice assistant. 
Keep your responses concise and natural-sounding. 
Respond in the same language the user speaks to you.
Be warm, engaging, and conversational.`,
};

// Health check endpoint
app.get('/api/health', (req, res) => {
    res.json({ status: 'ok', model: MODEL });
});

// WebSocket connection handler
wss.on('connection', async (clientWs) => {
    console.log('Client connected');

    let geminiSession = null;
    let isConnected = true;

    try {
        // Connect to Gemini Live API
        geminiSession = await ai.live.connect({
            model: MODEL,
            config: CONFIG,
            callbacks: {
                onopen: () => {
                    console.log('Connected to Gemini Live API');
                    if (isConnected && clientWs.readyState === WebSocket.OPEN) {
                        clientWs.send(JSON.stringify({ type: 'connected' }));
                    }
                },
                onmessage: (message) => {
                    if (!isConnected || clientWs.readyState !== WebSocket.OPEN) return;

                    // Handle audio response from Gemini
                    if (message.serverContent?.modelTurn?.parts) {
                        for (const part of message.serverContent.modelTurn.parts) {
                            if (part.inlineData?.data) {
                                // Send audio chunk to client
                                clientWs.send(JSON.stringify({
                                    type: 'audio',
                                    data: part.inlineData.data, // base64 encoded PCM
                                }));
                            }
                            if (part.text) {
                                // Send text for display
                                clientWs.send(JSON.stringify({
                                    type: 'text',
                                    data: part.text,
                                }));
                            }
                        }
                    }

                    // Handle turn complete
                    if (message.serverContent?.turnComplete) {
                        clientWs.send(JSON.stringify({ type: 'turnComplete' }));
                    }

                    // Handle interruption
                    if (message.serverContent?.interrupted) {
                        clientWs.send(JSON.stringify({ type: 'interrupted' }));
                    }
                },
                onerror: (error) => {
                    console.error('Gemini error:', error);
                    if (isConnected && clientWs.readyState === WebSocket.OPEN) {
                        clientWs.send(JSON.stringify({ type: 'error', message: error.message }));
                    }
                },
                onclose: (event) => {
                    console.log('Gemini connection closed:', event?.reason || 'Unknown reason');
                },
            },
        });

        console.log('Gemini session established');

    } catch (error) {
        console.error('Failed to connect to Gemini:', error);
        clientWs.send(JSON.stringify({ type: 'error', message: 'Failed to connect to AI' }));
        clientWs.close();
        return;
    }

    // Handle messages from client
    clientWs.on('message', async (data) => {
        try {
            const message = JSON.parse(data.toString());

            if (message.type === 'audio' && geminiSession) {
                // Forward audio to Gemini
                await geminiSession.sendRealtimeInput({
                    audio: {
                        data: message.data, // base64 encoded PCM
                        mimeType: 'audio/pcm;rate=16000',
                    },
                });
            }
        } catch (error) {
            console.error('Error processing client message:', error);
        }
    });

    // Handle client disconnect
    clientWs.on('close', () => {
        console.log('Client disconnected');
        isConnected = false;
        if (geminiSession) {
            geminiSession.close();
        }
    });

    clientWs.on('error', (error) => {
        console.error('Client WebSocket error:', error);
        isConnected = false;
    });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
    console.log(`🚀 Server running at http://localhost:${PORT}`);
    console.log(`📡 WebSocket endpoint: ws://localhost:${PORT}/ws`);
});
