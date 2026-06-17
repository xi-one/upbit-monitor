# Discord TTS Listener

이 폴더는 Discord 채널 메시지를 읽어서 로컬 PC에서 TTS로 읽는 스크립트를 담고 있다.

구성:

- `mac_discord_tts.py`
  - macOS 전용
  - macOS 기본 `say` 명령 사용
- `windows_discord_tts.py`
  - Windows 전용
  - `pyttsx3` 사용
- `.env.example`
  - 필요한 환경변수 예시
- `requirements.txt`
  - 전용 Python 패키지 목록

## 동작 방식

1. Discord 봇이 지정한 채널 메시지를 읽음
2. 메시지에서 종목명 패턴을 우선 추출
3. 종목명이 있으면 종목명을 읽음
4. 종목명이 없으면 메시지 전체를 읽음

현재 종목명 추출 예:

- `KRW-BTC`
- `BTC`
- `비트코인`

## Discord 봇 준비

1. Discord Developer Portal에서 새 앱 생성
2. Bot 추가
3. `MESSAGE CONTENT INTENT` 활성화
4. 봇을 서버에 초대
5. 읽을 채널 접근 권한 부여
6. Bot Token 복사

## 환경변수

`.env.example`를 복사해서 `.env`로 만들고 채운다.

필수:

- `DISCORD_BOT_TOKEN`
- `DISCORD_CHANNEL_ID` 또는 `DISCORD_CHANNEL_IDS`

선택:

- `DISCORD_CHANNEL_IDS=111111111111111111,222222222222222222`
  - 여러 채널 중 읽을 채널만 쉼표로 나열
  - 이 값이 있으면 `DISCORD_CHANNEL_ID`보다 우선 사용
- `DISCORD_TTS_ONLY_BOT_MESSAGES=true`
  - 봇 메시지만 읽고 싶을 때
- `DISCORD_TTS_USERNAME_PREFIX=true`
  - 읽을 때 작성자 이름도 같이 읽고 싶을 때
- `UPBIT_MARKET_ALL_URL=...`
  - 시작 시 종목명을 메모리에 불러올 업비트 API URL
- `DISCORD_TTS_MAC_VOICE=Yuna`
  - macOS `say` 음성 지정
- `DISCORD_TTS_WINDOWS_RATE=180`
  - Windows 읽기 속도

## 설치

```bash
cd discord_tts
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Windows PowerShell:

```powershell
cd discord_tts
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

## 실행

macOS:

```bash
cd discord_tts
source .venv/bin/activate
python mac_discord_tts.py
```

Windows:

```powershell
cd discord_tts
.venv\Scripts\Activate.ps1
python windows_discord_tts.py
```

## 종목명 읽기 방식

- 메시지에 `KRW-INJ` 같은 종목 코드가 있으면
- 실행 시작 시 업비트 API에서 불러온 종목명 맵에서 한글명을 찾아
- `인젝티브`처럼 읽는다

매핑을 찾지 못하면 기존처럼 종목 코드를 그대로 읽는다.

메시지를 읽을 때 콘솔에는 어떤 채널에서 어떤 종목이 감지됐는지도 같이 출력한다.

시작하면 듣고 있는 채널 ID와 채널명 매핑이 1회 출력된다.
채널명 색상은 채널마다 자동으로 다르게 배정된다.

예:

```text
listening channel map:
- 111111111111111111 -> #봇-알림
- 222222222222222222 -> #하따-알림
```

예:

```text
[2026-06-17 15:42:10] #봇-알림 인젝티브
```

## 참고

- 이 스크립트는 서버에서 실행하는 게 아니라, **알림을 들을 로컬 PC에서 실행**해야 한다.
- Discord 봇 토큰은 절대 Git에 올리면 안 된다.
