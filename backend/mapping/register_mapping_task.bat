@echo off
chcp 65001 >nul
REM 매일 08:15 가격 매핑 실행 등록 (크롤러 CareEatPriceCrawler 는 07:30~07:55 시작 → 08:00 전 반영)
schtasks /Create /F /SC DAILY /ST 08:15 /TN "CareEatPriceMapping" /TR "\"%~dp0run_daily.bat\""
if errorlevel 1 (
  echo 등록 실패. 이 파일을 마우스 오른쪽 버튼 - 관리자 권한으로 실행 해 보세요.
) else (
  echo 등록 완료: 작업 스케줄러에서 CareEatPriceMapping 확인
  echo 해제하려면: schtasks /Delete /TN "CareEatPriceMapping" /F
)
pause
