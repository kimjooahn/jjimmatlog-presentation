# 찐맛로그 발표 데모

## 인터넷에 배포하기 (Render)

이 저장소에는 Render 배포 설정(`render.yaml`)이 포함되어 있습니다. 배포한 뒤 발급되는 `https://...onrender.com` 주소로 다른 컴퓨터에서도 접속할 수 있습니다.

1. GitHub에서 이 저장소에 최신 변경사항을 올립니다.
2. [Render](https://render.com/)에 로그인하고 **New + → Blueprint**를 선택합니다.
3. GitHub 저장소 `202301505kgm/-1`를 연결하고 Blueprint를 생성합니다.
4. 배포가 끝나면 Render 대시보드에서 서비스 URL을 확인해 브라우저로 엽니다.

무료 서비스는 한동안 사용하지 않으면 잠들 수 있어, 다시 열 때 첫 접속이 늦어질 수 있습니다. 배포 서비스가 실행 중이어야 접속할 수 있습니다. 리뷰 사진과 외부 폰트는 접속하는 컴퓨터에 인터넷이 필요합니다.

## 내 컴퓨터에서 실행하기

프로젝트 폴더에서 Python 3을 사용할 수 있는 터미널을 열고 실행합니다.

```bash
python -m venv .venv
```

macOS/Linux:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python presentation_server.py
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe presentation_server.py
```

그 다음 `http://127.0.0.1:8765`를 엽니다. 이 주소는 해당 컴퓨터에서만 접속할 수 있습니다.
