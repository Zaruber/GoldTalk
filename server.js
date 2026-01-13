const express = require('express');
const app = express();
const fs = require('fs');
const https = require('https');
const path = require('path');

const PORT = 3000;

// SSL Certificates
const options = {
    key: fs.readFileSync('key.pem'),
    cert: fs.readFileSync('cert.pem')
};

const server = https.createServer(options, app);
const io = require('socket.io')(server);

// Serve static files from 'public' directory
app.use(express.static(path.join(__dirname, 'public')));

// Store connected users: socket.id -> nickname
const users = {};

io.on('connection', (socket) => {
    console.log('User connected:', socket.id);

    socket.on('join', (nickname) => {
        users[socket.id] = nickname || `Player_${socket.id.substr(0, 4)}`;
        io.emit('user_list', Object.values(users));
        io.emit('chat_message', {
            user: 'Console',
            text: `Player ${users[socket.id]} connected to the server.`,
            type: 'system'
        });

        // Notify other users that a new peer joined (for WebRTC)
        socket.broadcast.emit('peer_joined', socket.id);
    });

    socket.on('chat_message', (msg) => {
        const nickname = users[socket.id];
        if (nickname) {
            io.emit('chat_message', {
                user: nickname,
                text: msg,
                type: 'user'
            });
        }
    });

    // WebRTC Signaling
    socket.on('signal', (data) => {
        io.to(data.target).emit('signal', {
            sender: socket.id,
            data: data.data
        });
    });

    socket.on('disconnect', () => {
        const nickname = users[socket.id];
        if (nickname) {
            io.emit('chat_message', {
                user: 'Console',
                text: `Player ${nickname} dropped from server.`,
                type: 'system'
            });
            delete users[socket.id];
            io.emit('user_list', Object.values(users));
            io.emit('peer_left', socket.id);
        }
        console.log('User disconnected:', socket.id);
    });
});

server.listen(PORT, '0.0.0.0', () => {
    console.log(`Server running on https://0.0.0.0:${PORT}`);
});
