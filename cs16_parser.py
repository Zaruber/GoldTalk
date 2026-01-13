#!/usr/bin/env python3
"""
CS 1.6 Server Statistics Parser v3.0
Парсинг через WebAPI, RCON и прямой анализ протокола
"""

import socket
import struct
import json
import csv
import re
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import time
import threading

class CS16ServerParser:
    """Parser for CS 1.6 server info via multiple methods"""
    
    # A2S packet headers
    A2S_INFO = b'\xFF\xFF\xFF\xFFTSource Engine Query\x00'
    A2S_PLAYER = b'\xFF\xFF\xFF\xFFU'
    A2S_RULES = b'\xFF\xFF\xFF\xFFV'
    
    # Популярные игровые моды и серверные утилиты с API
    API_ENDPOINTS = {
        'gametracker': 'https://api.gametracker.com/api/v2/servers',
        'masterclan': 'https://www.masterclan.info/api/servers'
    }
    
    def __init__(self, timeout: int = 5):
        self.timeout = timeout
        self.servers = []
        self.lock = threading.Lock()
        
    def query_server_full(self, host: str, port: int) -> Optional[Dict]:
        """
        Полный запрос информации о сервере (INFO + PLAYERS)
        """
        server_info = self.query_server_info(host, port)
        if not server_info:
            return None
        
        # Получаем список игроков несколькими способами
        players = self.query_server_players_advanced(host, port)
        server_info['players_list'] = players
        server_info['online_players'] = len(players)
        
        return server_info
    
    def query_server_info(self, host: str, port: int) -> Optional[Dict]:
        """
        A2S_INFO запрос - информация о сервере (название, карта, игроки)
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)
            
            sock.sendto(self.A2S_INFO, (host, port))
            response, _ = sock.recvfrom(4096)
            sock.close()
            
            if len(response) < 6 or response[:4] != b'\xFF\xFF\xFF\xFF':
                return None
            
            # DEBUG: Log raw A2S_INFO response
            print(f"DEBUG RAW A2S_INFO ({len(response)} bytes): {response.hex()}")
            
            return self._parse_a2s_info(response, host, port)
                
        except socket.timeout:
            return None
        except Exception as e:
            return None
    
    def _parse_a2s_info(self, response: bytes, host: str, port: int) -> Optional[Dict]:
        """
        Парсинг A2S_INFO ответа
        """
        try:
            offset = 4
            
            if offset >= len(response) or response[offset] != 0x49:
                return None
            
            offset += 1
            
            if offset >= len(response):
                return None
            
            protocol = response[offset]
            offset += 1
            
            def read_string(data: bytes, pos: int) -> Tuple[str, int]:
                end = data.find(b'\x00', pos)
                if end == -1:
                    return '', len(data)
                return data[pos:end].decode('utf-8', errors='ignore'), end + 1
            
            server_name, offset = read_string(response, offset)
            map_name, offset = read_string(response, offset)
            game_dir, offset = read_string(response, offset)
            game_name, offset = read_string(response, offset)
            
            if offset + 6 > len(response):
                return {
                    'host': host,
                    'port': port,
                    'protocol': protocol,
                    'name': server_name,
                    'map': map_name,
                    'game_dir': game_dir,
                    'game_name': game_name,
                    'players': 'N/A',
                    'max_players': 'N/A',
                    'bots': 'N/A',
                    'timestamp': datetime.now().isoformat()
                }
            
            appid = struct.unpack('<H', response[offset:offset+2])[0]
            offset += 2
            
            players = response[offset]
            offset += 1
            
            max_players = response[offset]
            offset += 1
            
            bots = response[offset]
            offset += 1

            # Extended Info
            server_type = chr(response[offset]) if offset < len(response) else '?'
            offset += 1

            environment = chr(response[offset]) if offset < len(response) else '?'
            offset += 1

            visibility = response[offset] if offset < len(response) else 0
            offset += 1

            vac = response[offset] if offset < len(response) else 0
            offset += 1

            version, offset = read_string(response, offset)

            # Extra Data Flag (EDF)
            edf = response[offset] if offset < len(response) else 0
            offset += 1

            keywords = ''
            
            if edf & 0x80: # Port
                offset += 2
            
            if edf & 0x10: # SteamID
                offset += 8
            
            if edf & 0x40: # SourceTV
                offset += 2
                _, offset = read_string(response, offset) # SourceTV Name

            if edf & 0x20: # Keywords
                keywords, offset = read_string(response, offset)

            if edf & 0x01: # GameID
                offset += 8

            server_info = {
                'host': host,
                'port': port,
                'protocol': protocol,
                'name': server_type, # Temporary placeholder to debug logic if needed, but keeping logical name is better
                'name': server_name,
                'map': map_name,
                'game_dir': game_dir,
                'game_name': game_name,
                'appid': appid,
                'players': players,
                'max_players': max_players,
                'bots': bots,
                'free_slots': max(0, max_players - players),
                'timestamp': datetime.now().isoformat(),
                # New Fields
                'server_type': server_type,
                'environment': environment,
                'secure': bool(vac),
                'password': bool(visibility),
                'version': version,
                'tags': keywords
            }
            
            return server_info
        except Exception as e:
            return None
    
    def query_server_players_advanced(self, host: str, port: int) -> List[Dict]:
        """
        Продвинутый запрос игроков - несколько методов
        1. A2S_PLAYER (оригинальный)
        2. GameTracker API
        3. MasterClan API
        4. Прямой TCP подключение (рискованно)
        """
        # Метод 1: A2S_PLAYER
        players = self.query_server_players_a2s(host, port)
        if players:
            return players
        
        # Метод 2: API сервисов
        players = self.query_server_players_api(host, port)
        if players:
            return players
        
        # Метод 3: WebAPI (если доступен)
        players = self.query_server_players_web(host, port)
        if players:
            return players
        
        return []
    
    def query_server_players_a2s(self, host: str, port: int) -> List[Dict]:
        """
        A2S_PLAYER запрос с улучшенной обработкой (попытка двух методов challenge)
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)
            
            # Strategy:
            # 1. Try to get Challenge using 0x55 with -1 (Standard)
            # 2. Try to get Challenge using 0x57 (Old)
            # 3. If we get a challenge, send the actual query
            
            challenge = None
            
            # Attempt 1: Standard A2S_PLAYER challenge request
            try:
                # Send 0xFFFFFFFF 0x55 0xFFFFFFFF (Request Challenge)
                sock.sendto(b'\xFF\xFF\xFF\xFF\x55\xFF\xFF\xFF\xFF', (host, port))
                response, _ = sock.recvfrom(4096)
                print(f"DEBUG RAW PLAYER RESP 1 ({len(response)} bytes): {response.hex()}")
                
                # Check for S2C_CHALLENGE (0x41)
                if len(response) >= 5 and response[:4] == b'\xFF\xFF\xFF\xFF' and response[4] == 0x41:
                    challenge = response[5:9]
            except socket.timeout:
                print("DEBUG: Method 1 Timeout")
                pass
            
            # Attempt 2: Old "Get Challenge" 0x57
            if not challenge:
                try:
                    sock.sendto(b'\xFF\xFF\xFF\xFF\x57', (host, port))
                    response, _ = sock.recvfrom(4096)
                    print(f"DEBUG RAW PLAYER RESP 2 ({len(response)} bytes): {response.hex()}")
                    
                    if len(response) >= 5 and response[:4] == b'\xFF\xFF\xFF\xFF' and response[4] == 0x41:
                         challenge = response[5:9]
                except socket.timeout:
                    print("DEBUG: Method 2 Timeout")
                    pass

            if challenge:
                print(f"DEBUG: Got Challenge {challenge.hex()}, sending query...")
                # Send Query with Challenge
                sock.sendto(self.A2S_PLAYER + challenge, (host, port))
                try:
                    response, _ = sock.recvfrom(4096)
                    print(f"DEBUG RAW FINAL RESP ({len(response)} bytes): {response.hex()}")
                    
                    # Accept both 0x55 ('U') and 0x44 ('D')
                    if len(response) >= 5 and response[:4] == b'\xFF\xFF\xFF\xFF' and (response[4] == 0x55 or response[4] == 0x44):
                        return self._parse_a2s_players(response)
                except socket.timeout:
                     print("DEBUG: Final Query Timeout")
            else:
                 print("DEBUG: Failed to get challenge")

            sock.close()
            return []
        except Exception as e:
            print(f"Error querying players: {e}")
            return []
    
    def _parse_a2s_players(self, response: bytes) -> List[Dict]:
        """
        Парсинг A2S_PLAYER ответа
        """
        try:
            players = []
            
            # 0x55 (Source/Modern) or 0x44 (GoldSrc/Legacy)
            if response[4] != 0x55 and response[4] != 0x44:
                return []
            
            offset = 5
            
            if offset >= len(response):
                return []
            
            player_count = response[offset]
            offset += 1
            
            for i in range(player_count):
                if offset >= len(response):
                    break
                
                index = response[offset]
                offset += 1
                
                end = response.find(b'\x00', offset)
                if end == -1:
                    break
                
                name = response[offset:end].decode('utf-8', errors='ignore')
                offset = end + 1
                
                if offset + 8 > len(response):
                    break
                
                score = struct.unpack('<i', response[offset:offset+4])[0]
                offset += 4
                
                time_played = struct.unpack('<f', response[offset:offset+4])[0]
                offset += 4
                
                players.append({
                    'index': index,
                    'name': name,
                    'score': score,
                    'time_seconds': round(time_played, 1),
                    'time_formatted': self._format_time(time_played),
                    'source': 'A2S'
                })
            
            return players
        except:
            return []
    
    def query_server_players_api(self, host: str, port: int) -> List[Dict]:
        """
        Запрос через публичные API сервисы
        """
        try:
            # GameTracker API
            url = f"https://api.gametracker.com/api/v2/servers/csgo/{host}:{port}/players"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            response = urllib.request.urlopen(req, timeout=self.timeout)
            data = json.loads(response.read().decode())
            
            if 'players' in data:
                players = []
                for player in data['players']:
                    players.append({
                        'name': player.get('name', 'Unknown'),
                        'score': player.get('score', 0),
                        'time_seconds': player.get('time', 0),
                        'time_formatted': self._format_time(player.get('time', 0)),
                        'source': 'GameTracker'
                    })
                return players
        except:
            pass
        
        return []
    
    def query_server_players_web(self, host: str, port: int) -> List[Dict]:
        """
        Попытка получить данные со встроенного web-интерфейса сервера
        """
        try:
            urls = [
                f"http://{host}:{port}/api/players",
                f"http://{host}:27005/api/players",
                f"http://{host}:8080/players",
                f"http://{host}:80/admin/players.html"
            ]
            
            for url in urls:
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    response = urllib.request.urlopen(req, timeout=2)
                    data = response.read().decode()
                    
                    # Парсим JSON если это API
                    try:
                        json_data = json.loads(data)
                        if isinstance(json_data, list):
                            return json_data
                        elif 'players' in json_data:
                            return json_data['players']
                    except:
                        # Парсим HTML таблицу
                        players = self._parse_html_players(data)
                        if players:
                            return players
                except:
                    continue
        except:
            pass
        
        return []
    
    def _parse_html_players(self, html: str) -> List[Dict]:
        """
        Парсинг HTML таблицы игроков (для встроенного interface)
        """
        try:
            players = []
            
            # Поиск строк таблицы с информацией об игроках
            rows = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
            
            for row in rows:
                cells = re.findall(r'<td[^>]*>([^<]*)</td>', row)
                
                if len(cells) >= 3:
                    name = cells[0].strip()
                    try:
                        score = int(cells[1].strip())
                    except:
                        score = 0
                    
                    if name and name != 'Name':  # Пропускаем заголовок
                        players.append({
                            'name': name,
                            'score': score,
                            'time_formatted': 'N/A',
                            'source': 'Web'
                        })
            
            return players if players else []
        except:
            return []
    
    def _format_time(self, seconds: float) -> str:
        """Форматирование времени"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"
    
    def query_known_servers(self, servers_list: List[Tuple[str, int]], 
                           use_threading: bool = True) -> List[Dict]:
        """
        Запрос информации с известных серверов
        """
        results = []
        total = len(servers_list)
        
        if use_threading and total > 1:
            threads = []
            
            def worker(host, port, idx):
                print(f"[{idx}/{total}] {host}:{port}...", end=" ", flush=True)
                server_info = self.query_server_full(host, port)
                if server_info:
                    print(f"✓ ({server_info.get('players', 0)} игроков)")
                    with self.lock:
                        results.append(server_info)
                else:
                    print("✗")
            
            for idx, (host, port) in enumerate(servers_list, 1):
                t = threading.Thread(target=worker, args=(host, port, idx))
                threads.append(t)
                t.start()
            
            for t in threads:
                t.join()
        else:
            for idx, (host, port) in enumerate(servers_list, 1):
                print(f"[{idx}/{total}] {host}:{port}...", end=" ", flush=True)
                server_info = self.query_server_full(host, port)
                if server_info:
                    print(f"✓ ({server_info.get('players', 0)} игроков)")
                    results.append(server_info)
                else:
                    print("✗")
                
                time.sleep(0.2)
        
        return results
    
    def save_json(self, data: List[Dict], filename: str = 'cs16_servers.json'):
        """Сохранение результатов в JSON"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✓ Сохранено в {filename}")
    
    def save_csv(self, data: List[Dict], filename: str = 'cs16_servers.csv'):
        """Сохранение результатов в CSV"""
        if not data:
            return
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['IP', 'Port', 'Сервер', 'Карта', 'Игроки', 'Макс', 'Боты', 'Свобод', 'Время запроса'])
            
            for server in data:
                writer.writerow([
                    server.get('host', ''),
                    server.get('port', ''),
                    server.get('name', '')[:30],
                    server.get('map', ''),
                    server.get('players', 0),
                    server.get('max_players', 0),
                    server.get('bots', 0),
                    server.get('free_slots', 0),
                    server.get('timestamp', '')
                ])
        
        print(f"✓ Сохранено в {filename}")
    
    def save_players_csv(self, data: List[Dict], filename: str = 'cs16_players.csv'):
        """Сохранение списка игроков в CSV"""
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['IP:Port', 'Сервер', 'Игрок', 'Счёт', 'Время игры', 'Источник', 'Время запроса'])
            
            for server in data:
                server_addr = f"{server.get('host')}:{server.get('port')}"
                server_name = server.get('name', '')[:20]
                
                players_list = server.get('players_list', [])
                if players_list:
                    for player in players_list:
                        writer.writerow([
                            server_addr,
                            server_name,
                            player.get('name', '')[:30],
                            player.get('score', 0),
                            player.get('time_formatted', 'N/A'),
                            player.get('source', 'Unknown'),
                            server.get('timestamp', '')
                        ])
                else:
                    writer.writerow([server_addr, server_name, '-', '-', '-', 'None', server.get('timestamp', '')])
        
        print(f"✓ Сохранено в {filename}")
    
    def print_stats(self, data: List[Dict]):
        """Вывод статистики"""
        print("\n" + "="*90)
        print(f"СТАТИСТИКА: Найдено активных серверов: {len(data)}")
        print("="*90)
        
        for i, server in enumerate(data, 1):
            print(f"\n{i}. {server.get('name', 'Unknown')}")
            print(f"   IP:Port: {server.get('host')}:{server.get('port')}")
            print(f"   Карта: {server.get('map', 'N/A')}")
            print(f"   Игроки: {server.get('players', 0)}/{server.get('max_players', 0)} (Боты: {server.get('bots', 0)})")
            print(f"   Свободных слотов: {server.get('free_slots', 0)}")
            
            players_list = server.get('players_list', [])
            if players_list:
                print(f"   Найдено игроков: {len(players_list)}")
                print(f"   TOP-10 игроков:")
                sorted_players = sorted(players_list, key=lambda x: x.get('score', 0), reverse=True)[:10]
                for j, player in enumerate(sorted_players, 1):
                    print(f"      {j:2}. {player['name'][:28]:28} | Счёт: {player['score']:5} | Время: {player['time_formatted']:8} | {player.get('source', 'N/A')}")
            else:
                print(f"   ⚠ Игроки не получены (API недоступен)")
            
            print(f"   Запрос: {server.get('timestamp', 'N/A')}")


# Основной блок
if __name__ == "__main__":
    parser = CS16ServerParser(timeout=5)
    
    print("╔" + "═"*88 + "╗")
    print("║" + " CS 1.6 Server Statistics Parser v3.0 - Advanced".center(88) + "║")
    print("╚" + "═"*88 + "╝")
    
    known_servers = [
        ("62.122.213.158", 27015),
        ("46.174.54.40", 27015),
        ("62.122.215.3", 27015),
    ]
    
    print(f"\nЗапрос {len(known_servers)} серверов с расширенным парсингом...")
    print("(A2S Protocol + API + Web Interface)\n")
    
    results = parser.query_known_servers(known_servers, use_threading=True)
    
    parser.save_json(results, 'competitors_full.json')
    parser.save_csv(results, 'competitors_servers.csv')
    parser.save_players_csv(results, 'competitors_players.csv')
    
    parser.print_stats(results)
    
    print("\n" + "="*90)
    print("✓ ВСЕ РЕЗУЛЬТАТЫ СОХРАНЕНЫ!")
    print("  • competitors_full.json - полные данные (JSON)")
    print("  • competitors_servers.csv - информация о серверах")
    print("  • competitors_players.csv - список игроков и их счёт")
    print("="*90)