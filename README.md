# Day 06 · Data Ingestion Engineering

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.

---

## Triển khai & tái lập kết quả (Implemented Pipeline & Reproducibility)

- **Corpus (`data/manifest.json`):** 2 tài liệu công khai của NIST — `NIST.AI.100-1.pdf` (`nist-ai-100-1`, 2023, 42 trang hợp lệ) và `NIST.AI.600-1.pdf` (`nist-ai-600-1`, 2024, 53 trang hợp lệ), tổng **95 trang nội dung hợp lệ** đặt trong `starter/data/`.
- **Môi trường & phụ thuộc đã kiểm thử:** Python `3.11.9` (`psycopg 3.3.8`, `pypdf 6.21.4`, `python-dotenv 1.2.4`, `openai 2.54.0` — khai báo trong [starter/requirements.txt](starter/requirements.txt)), PostgreSQL `16.16` + `pgvector 0.8.7` qua Docker Compose (`127.0.0.1:55433`), embedding OpenAI `text-embedding-3-small` (1536 chiều, metric Cosine `<=>`).
- **Cài đặt và chạy lại (Windows PowerShell):**
  1. Khởi động database (nếu `docker` chưa có trong `PATH`, dùng đường dẫn Docker Desktop `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe`):
     ```powershell
     cd starter
     docker compose -p day6_student_starter up -d --wait
     ```
  2. Tạo `starter\.env` từ `starter\.env.example` và điền `OPENAI_API_KEY`.
  3. Tạo virtualenv và cài thư viện:
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\pip install -r requirements.txt
     .\.venv\Scripts\python.exe scripts\check_setup.py
     ```
  4. Chạy ingest + benchmark `dev` + trích xuất mẫu coherence + kiểm tra idempotency:
     ```powershell
     .\.venv\Scripts\python.exe -m src.run --split dev
     ```
  5. Chạy đánh giá toàn bộ (`dev` + `test` đóng băng) không ingest lại:
     ```powershell
     .\.venv\Scripts\python.exe -m src.run --split all --skip-ingest
     ```
- **Kết quả & nhãn đánh giá:**
  - Thông tin học viên & báo cáo: [STUDENT.md](STUDENT.md), [report/individual/2A202603932_NguyenVanHau.md](report/individual/2A202603932_NguyenVanHau.md)
  - Tổng hợp thí nghiệm: [artifacts/experiment_log.csv](artifacts/experiment_log.csv)
  - Bộ câu hỏi & tiêu chí chốt trước khi chạy: [benchmark/questions.json](benchmark/questions.json), [benchmark/README.md](benchmark/README.md)
  - Metrics, traces & audit thủ công: `starter/results/` (thư mục output trực tiếp của `starter/src/run.py`) và bản đồng bộ đầy đủ tại `results/` ở thư mục gốc (`summary_all.json`, `run_metadata_dev.json`, `run_metadata_all.json`, `coherence_samples.json`, `test_audit_extract.json`, `audit_coherence.csv`, `audit_metadata.csv`, `audit_grounding.csv`)
