const socket = io();

// DOM Elements
const loginScreen = document.getElementById('login-screen');
const chatScreen = document.getElementById('chat-screen');
const nicknameInput = document.getElementById('nickname-input');
const connectBtn = document.getElementById('connect-btn');
const consoleOutput = document.getElementById('console-output');
const serverLogs = document.getElementById('server-logs');
const messageInput = document.getElementById('message-input');
const userList = document.getElementById('user-list');
const voiceBtn = document.getElementById('voice-btn');
const voiceStatus = document.getElementById('voice-status');
const serverNameSpan = document.getElementById('current-server-name');
const mapNameSpan = document.getElementById('current-map-name');
const tabBtns = document.querySelectorAll('.tab-btn');

let localStream;
const peers = {}; // socketId -> RTCPeerConnection

// Tab Switching
tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        // Remove active class from buttons
        tabBtns.forEach(b => b.classList.remove('active'));
        // Hide all content
        document.querySelectorAll('.chat-content').forEach(c => c.classList.add('hidden'));

        // Activate clicked
        btn.classList.add('active');
        const tabId = btn.getAttribute('data-tab');
        document.getElementById(tabId).classList.remove('hidden');
    });
});

// Helper to log to 'console' (Chat Tab)
function logToChat(text, type = 'system', user = '') {
    const line = document.createElement('div');
    line.className = `console-line ${type}`;
    if (user) {
        line.innerHTML = `<span class="name">${user}:</span> ${text}`;
    } else {
        line.textContent = text;
    }
    consoleOutput.appendChild(line);
    consoleOutput.scrollTop = consoleOutput.scrollHeight;
}

// Helper to log to 'server logs' (Logs Tab)
function logToServerLogs(text) {
    const line = document.createElement('div');
    line.className = `console-line console`;
    line.textContent = `[Log] ${text}`;
    serverLogs.appendChild(line);
    serverLogs.scrollTop = serverLogs.scrollHeight;
}

// Connect Handler
connectBtn.addEventListener('click', () => {
    const nickname = nicknameInput.value.trim();
    const serverIp = document.getElementById('server-input').value.trim();

    if (nickname) {
        socket.emit('join_game', { nickname: nickname, server_ip: serverIp });
        loginScreen.classList.add('hidden');
        chatScreen.classList.remove('hidden');
        // Initial system message
        logToChat(`Подключение к реле...`, 'system');
        messageInput.focus();
    }
});

// Chat handlers
messageInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        const msg = messageInput.value.trim();
        if (msg) {
            socket.emit('chat_message', msg);
            messageInput.value = '';
        }
    }
});

socket.on('chat_message', (data) => {
    // data: { user, text, type }
    if (data.type === 'console' || data.type === 'error') {
        logToServerLogs(data.text);
    }

    // System messages go to both or specific depending on importance
    if (data.type === 'system') {
        logToChat(data.text, 'system');
        if (data.text.includes('Connecting') || data.text.includes('Connected')) {
            logToServerLogs(data.text);
        }
    }

    // User chat
    if (data.type === 'user' || data.type === 'game') {
        logToChat(data.text, data.type, data.user);
    }
});

socket.on('server_info', (info) => {
    if (info) {
        // Update Header
        if (info.name) serverNameSpan.textContent = info.name;
        if (info.map) mapNameSpan.textContent = info.map;

        // Update Info Tab
        document.getElementById('info-name').textContent = info.name || '-';
        document.getElementById('info-map').textContent = info.map || '-';

        const playersCount = info.players !== undefined ? `${info.players}/${info.max_players}` : '-';
        const botsCount = info.bots !== undefined ? ` (Боты: ${info.bots})` : '';
        document.getElementById('info-players').textContent = playersCount + botsCount;

        // VAC
        const vacEl = document.getElementById('info-secure');
        vacEl.textContent = info.secure ? "Защищен (VAC)" : "Не защищен";
        vacEl.style.color = info.secure ? "#00cc00" : "#ff4444";

        // OS
        const osMap = { 'l': 'Linux', 'w': 'Windows', 'm': 'Mac', 'o': 'Mac' };
        document.getElementById('info-os').textContent = osMap[info.environment] || info.environment || '-';

        // Password
        const passEl = document.getElementById('info-password');
        passEl.textContent = info.password ? "Да (Приватный)" : "Нет (Публичный)";
        passEl.style.color = info.password ? "#ffac30" : "#00cc00";

        // Type
        const typeMap = { 'd': 'Dedicated', 'l': 'Listen', 'p': 'Proxy' };
        document.getElementById('info-type').textContent = typeMap[info.server_type] || info.server_type || '-';

        document.getElementById('info-version').textContent = info.version || '-';
        document.getElementById('info-tags').textContent = info.tags || '-';
    }
});

// User list (Scoreboard)
socket.on('player_list_update', (players) => {
    userList.innerHTML = '';
    // Sort by score (Frags) descending
    players.sort((a, b) => b.score - a.score);

    players.forEach(player => {
        const li = document.createElement('li');
        li.style.display = 'flex';
        li.style.justifyContent = 'space-between';

        const nameSpan = document.createElement('span');
        nameSpan.textContent = player.name;
        nameSpan.style.overflow = 'hidden';
        nameSpan.style.textOverflow = 'ellipsis';
        nameSpan.style.whiteSpace = 'nowrap';
        nameSpan.style.maxWidth = '140px';
        nameSpan.title = player.name; // Tooltip

        const scoreSpan = document.createElement('span');
        scoreSpan.textContent = player.score;
        scoreSpan.style.color = '#ffac30';

        li.appendChild(nameSpan);
        li.appendChild(scoreSpan);
        userList.appendChild(li);
    });
});


// Voice Chat Logic (WebRTC) - Simplified for brevity, same logic as before but localized
const rtcConfig = {
    iceServers: [
        { urls: 'stun:stun.l.google.com:19302' }
    ]
};

async function initVoice() {
    try {
        localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        voiceStatus.textContent = "Голос: ВКЛ (Слушаю)";
        voiceStatus.style.color = "#00cc00";
        voiceBtn.textContent = "Отключить";
        logToServerLogs(`Микрофон инициализирован.`);
    } catch (err) {
        logToServerLogs(`Ошибка микрофона: ${err.message}`);
        console.error(err);
    }
}

// Handle new peer joining
socket.on('peer_joined', async (peerId) => {
    if (!localStream) return;
    createPeerConnection(peerId, true);
});

socket.on('signal', async (data) => {
    const { sender, data: signalData } = data;
    if (!peers[sender]) {
        createPeerConnection(sender, false);
    }
    const peer = peers[sender];

    if (signalData.type === 'offer') {
        await peer.setRemoteDescription(new RTCSessionDescription(signalData));
        const answer = await peer.createAnswer();
        await peer.setLocalDescription(answer);
        socket.emit('signal', { target: sender, data: peer.localDescription });
    } else if (signalData.type === 'answer') {
        await peer.setRemoteDescription(new RTCSessionDescription(signalData));
    } else if (signalData.candidate) {
        try { await peer.addIceCandidate(new RTCIceCandidate(signalData)); } catch (e) { }
    }
});

socket.on('peer_left', (peerId) => {
    if (peers[peerId]) {
        peers[peerId].close();
        delete peers[peerId];
    }
});

function createPeerConnection(peerId, isInitiator) {
    const peer = new RTCPeerConnection(rtcConfig);
    peers[peerId] = peer;
    if (localStream) {
        localStream.getTracks().forEach(track => peer.addTrack(track, localStream));
    }
    peer.ontrack = (event) => {
        const remoteAudio = new Audio();
        remoteAudio.srcObject = event.streams[0];
        remoteAudio.autoplay = true;
    };
    peer.onicecandidate = (event) => {
        if (event.candidate) {
            socket.emit('signal', { target: peerId, data: event.candidate });
        }
    };
    if (isInitiator) {
        peer.onnegotiationneeded = async () => {
            const offer = await peer.createOffer();
            await peer.setLocalDescription(offer);
            socket.emit('signal', { target: peerId, data: peer.localDescription });
        };
    }
    return peer;
}

voiceBtn.addEventListener('click', () => {
    if (!localStream) {
        initVoice();
    } else {
        localStream.getAudioTracks()[0].enabled = !localStream.getAudioTracks()[0].enabled;
        const isEnabled = localStream.getAudioTracks()[0].enabled;
        voiceStatus.textContent = isEnabled ? "Голос: ВКЛ" : "Голос: МУТ";
        voiceStatus.style.color = isEnabled ? "#00cc00" : "#ffac30";
        voiceBtn.textContent = isEnabled ? "Мут" : "Размут";
    }
});
