# Báo cáo cá nhân — Day 6

- **Họ và tên:** Nguyễn Văn Hậu
- **MSSV:** 2A202603932
- **Lớp:** L3B

## Dữ liệu và pipeline
- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - **Chủ đề:** Quản trị rủi ro AI & Generative AI trong hệ thống tiêu chuẩn NIST AI RMF (`data/manifest.json`).
  - **Hai tài liệu nguồn hợp lệ:**
    1. `nist-ai-100-1` — *Artificial Intelligence Risk Management Framework (AI RMF 1.0)* (tháng 1/2023, `starter/data/NIST.AI.100-1.pdf`, DOI `10.6028/NIST.AI.100-1`, SHA-256 `7576edb531d9848825814ee88e28b1795d3a84b435b4b797d3670eafdc4a89f1`).
    2. `nist-ai-600-1` — *AI RMF: Generative Artificial Intelligence Profile* (tháng 7/2024, `starter/data/NIST.AI.600-1.pdf`, DOI `10.6028/NIST.AI.600-1`, SHA-256 `6e73620ab6b64e90ef2c04bf0e0d6246185a2f4b1b13cab0df494496cff89b6a`).
  - **Quyền sử dụng:** Công trình Chính phủ Hoa Kỳ (`17 U.S.C. § 105`, phạm vi công cộng tại Hoa Kỳ; quyền phân phối/tái bản miễn phí toàn cầu theo chính sách NIST Technical Series), truy cập `2026-11-14T09:44:00+07:00`. Không chứa dữ liệu cá nhân hay tài liệu mật.
  - **Quy tắc tính trang & tổng số trang:** Đếm các trang vật lý PDF được `pypdf` trích xuất sạch và chứa nội dung thân bài hoặc phụ lục thực chất; loại bìa, trang bản quyền/lời cảm ơn, mục lục (TOC), danh mục hình, bìa sau và trang chỉ liệt kê tài liệu tham khảo (*Appendix B: References* trang 58–64 của `NIST.AI.600-1.pdf`). Tổng cộng **95 trang nội dung hợp lệ** (**42 trang** từ `100-1` trang 6–47/48; **53 trang** từ `600-1` trang 5–57/64), **0 trang rỗng**.
- **Chuẩn hóa, lỗi và giới hạn (`starter/src/ingestion.py`):**
  - Áp dụng chuẩn hóa Unicode `NFKC` (mở rộng ligature `fi/fl`), xóa header/footer lặp lại, nối từ bị ngắt gạch nối cuối dòng (`de-hyphenation`) nhưng giữ lại dấu nối của từ ghép hợp lệ, và tái tạo ranh giới đoạn `\n\n` dựa trên độ dài dòng gốc và tiêu đề cấu trúc. Lý do: `pypdf` chế độ mặc định xuất toàn bộ xuống dòng đơn (`double_nls = 0`) trong khi chế độ `layout` làm xáo trộn cột của các bảng 2–3 cột trong tài liệu NIST.
  - Pipeline kiểm tra và ghi lại các lỗi `out_of_range`, `extraction_error`, `empty_page` vào `results/ingestion_log.json`: tải đủ `95` trang hợp lệ, **0 lỗi parse** (`parse_seconds: 3.1014` ở lần chạy xác minh mới nhất).
  - **Giới hạn ghi nhận trung thực:** (1) Trang 12 của `NIST.AI.600-1.pdf` có lỗi khoảng trắng gốc trong PDF (`energy-and carbon-i ntensive th an`); (2) ingest theo từng trang vật lý chưa nối câu vắt qua ranh giới trang (thể hiện rõ tại `nist-ai-600-1` p.52→p.53, khiến đầu trang p.53 bắt đầu giữa câu `"early lifecycle TEVV approaches..."`).
- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy, idempotency và chi phí:**
  - **Phiên bản môi trường đã chạy:** Python `3.11.9`, `psycopg 3.3.8`, `pypdf 6.21.4`, `python-dotenv 1.2.4`, `openai 2.54.0`.
  - **Embedding & cách xử lý query/document:** OpenAI `text-embedding-3-small`, `1536` chiều (`starter/src/embeddings.py`, báo lỗi tường minh khi thiếu API key/sai chiều, không fallback sang vector giả). Là model đối xứng nên không cần tiền tố asymmetric: tài liệu được embed theo batch `64` chunk qua `embed_documents()`, câu hỏi embed đơn qua `embed_query()`. Cả 3 chiến lược dùng chung đúng 1 model và cùng tập vector câu hỏi trong mỗi lần chạy.
  - **Vector store, metric & xử lý tài liệu thay đổi:** PostgreSQL `16.16` + `pgvector 0.8.7` chạy trong Docker trên `127.0.0.1:55433` (bảng `rag_chunks`, cột `embedding vector(1536)`), tìm kiếm khoảng cách Cosine **chính xác** (`<=>`, không dùng chỉ mục xấp xỉ ANN).
    - **Chống trùng & cập nhật tài liệu đổi:** `PgVectorStore.upsert()` khóa chính `(strategy, chunk_id)` dùng `ON CONFLICT DO UPDATE` (cập nhật text, `content_hash` SHA-256, `metadata`, `embedding`) và xóa các chunk dư thừa (`DELETE ... WHERE strategy = %s AND document_id = %s AND NOT (chunk_id = ANY(%s))`) khi tài liệu thay đổi số chunk, kèm `prune_missing_documents=True` khi bỏ tài liệu khỏi manifest. Kiểm chứng thực tế trên B cho kết quả nạp lại `328 -> 328` chunk (không nhân đôi) và probe rút gọn chunk giảm `2 -> 1` (`passed: true`, `results/run_metadata_dev.json`).
  - **Lệnh chạy (từ `starter/`) & thời điểm chạy:**
    - Khởi động DB & kiểm tra kết nối: `docker compose -p day6_student_starter up -d --wait`, sau đó `.\.venv\Scripts\python.exe scripts\check_setup.py`
    - Chạy `dev` (`2026-11-14T03:01:15Z`, `results/run_metadata_dev.json`): `.\.venv\Scripts\python.exe -m src.run --split dev`
    - Chạy toàn bộ `dev + test` đóng băng (`2026-11-14T03:28:39Z`, `skip_ingest: false`, `results/run_metadata_all.json`): `.\.venv\Scripts\python.exe -m src.run --split all` (có thể dùng thêm `--skip-ingest` nếu chỉ cần chạy lại phần eval)
  - **Chi phí & thời gian thực tế (`results/run_metadata_all.json` & `results/run_metadata_dev.json`):**
    - Lần chạy toàn phần (`all`, `skip_ingest: false`): ingest A mất `8.068s` (`7.196s` embed + `0.873s` DB, `49,366` tokens, `$0.000987`), B mất `2.772s` (`2.296s` embed + `0.476s` DB, `44,429` tokens, `$0.000889`), C mất `0.376s` DB upsert (`0` token embedding thêm do tái dùng chunk B, `$0.0`); embed chung `22` câu query mất `4.249s` (`487` tokens, `$0.000010`), SQL search `A: 0.8553s`, `B: 0.7047s`, `C: 0.7838s`. Tổng chi phí lần chạy toàn phần là `$0.001886` (`94,282` prompt tokens, `< $0.002`).
    - Tham chiếu lần chạy `dev` trước đó (`03:01:15Z`): ingest `A: 7.383s`, `B: 3.785s`, `C: 0.956s`; embed `17` câu query hết `3.543s` (`379` tokens, `$0.000008`), SQL search `A: 1.2072s`, `B: 1.033s`, `C: 0.843s` (tổng `$0.001883`, `94,174` tokens).
- **Metadata bắt buộc, trường lọc bổ sung, kiểu dữ liệu, nguồn giá trị và lý do chọn:**
  - **Bắt buộc:** `document_id` (`str`, từ `source_id` trong `manifest.json`), `source` (`str`, đường dẫn PDF), `page` (`int`, trang vật lý 1-based).
  - **Bổ sung phục vụ lọc & truy vết:** `year` (`int`: `2023`/`2024`, từ `manifest.json`), `document_type` (`str`: `core_framework`/`genai_profile`, từ `manifest.json`), `section` (`str`: `executive_summary`, `introduction`, `foundational`, `genai_risks`, `govern`, `map`, `measure`, `manage`, `profiles`, `appendix` — trích xuất xác định từ tiêu đề mục/bảng NIST bằng `detect_section_from_text`), cùng JSONB `version` (`str`), `language` (`str`), `title` (`str`), `char_start`/`char_end` (`int` ở A), `chunk_length` (`int`), `raw_chars`/`normalized_chars` (`int`).
  - **Lý do chọn & hạn chế của metadata:** Cả hai tài liệu NIST chia sẻ cùng 4 hàm cốt lõi (`GOVERN`, `MAP`, `MEASURE`, `MANAGE`), nên `year`/`document_type` giúp phân tách khung gốc 2023 với phụ lục GenAI 2024, còn `section` khoanh đúng vòng đời quản trị rủi ro. **Hạn chế:** (1) bộ tách `section` dựa trên regex nhận diện tiêu đề chuẩn của NIST nên khó khái quát nguyên trạng sang tài liệu ngoài chuẩn, và chỉ gán một nhãn `section` cho toàn chunk nên các đoạn tham chiếu chéo (vd. Appendix nhắc lại GOVERN) vẫn mang nhãn nơi đoạn xuất hiện; (2) `year`/`document_type` chỉ có 2 giá trị nên chỉ phát huy tác dụng khi câu hỏi/ngữ cảnh nêu phạm vi đủ rõ.

## Cấu hình và benchmark
- **Chiến lược A / B / C (khác biệt duy nhất B–C):**
  - **A (`fixed`):** Cắt cứng `fixed_size(size=500, overlap=50)` ký tự, lưu đủ metadata nhưng **không lọc** lúc truy vấn (`559` chunks; min `52`, median `500`, mean `465.7`, max `500` ký tự).
  - **B (`para`):** Cắt theo đoạn văn/mục bảng `by_paragraph(max_size=1000)` có xả khi đổi `section`, **không lọc** lúc truy vấn (`328` chunks; min `15`, median `808.0`, mean `722.0`, max `999` ký tự).
  - **C (`para` + filter):** Dùng **cùng tập 328 chunk và vector của B**; khác biệt duy nhất so với B là áp dụng `SQL WHERE` tham số hóa trên whitelist (`year`, `document_type`, `section`, `document_id`) khi câu hỏi có `filter`. Các câu không có `filter` vẫn chạy không lọc y như B.
- **Bộ benchmark (`benchmark/questions.json`, `benchmark/README.md`):**
  - **22 câu hỏi** (`q01`–`q22`), chia cố định trước khi chạy: **17 câu `dev`** (`q01`–`q17`) và **5 câu `test` giữ kín** (`q18`–`q22`).
  - Phủ các dạng trực tiếp (`truc_tiep`), diễn đạt lại (`dien_dat_lai`), điều kiện/ngoại lệ (`dieu_kien_ngoai_le`) và **5 câu `metadata_filter`** (`q15`, `q16`, `q17` ở `dev`; `q21`, `q22` ở `test`).
  - **Kiểm chứng bằng chứng & giả định filter:** Mọi `evidence_quote` được kiểm tra khớp chính xác theo chuỗi con trên văn bản đã chuẩn hóa của `(gold_source_id, gold_page)` trước mọi lần chạy. Trong các câu filter (`q15`–`q17`, `q21`–`q22`), giá trị `filter` (`year`, `document_type`, `section`) là **input giả định do ngữ cảnh/người dùng cung cấp trước khi truy xuất**, hoàn toàn không chứa `gold_source_id` hay cụm từ từ `expected_answer`.
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test (`benchmark/README.md`):**
  1. Chính: `Evidence Hit@3` cao nhất trên `dev` (hòa xét `Hit@1` trên `dev`).
  2. Phụ: Điểm thủ công **Grounding** và **Coherence** cao hơn.
  3. Ưu tiên sau cùng: Số chunk, chi phí và độ trễ ingest thấp hơn khi chất lượng tương đương.

## Kết quả
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 9/17 (52.9%) | 11/17 (64.7%) | 559 | 7.383s ingest + 1.207s search (`run_metadata_dev`) | `$0.000987` ingest |
| A | test | 2/5 (40.0%) | 2/5 (40.0%) | 559 | 8.068s ingest + 0.855s search / 22q (`run_metadata_all`) | `$0.000987` ingest + dùng chung `$0.000010` (22q) |
| B | dev | 11/17 (64.7%) | 13/17 (76.5%) | 328 | 3.785s ingest + 1.033s search (`run_metadata_dev`) | `$0.000889` ingest |
| B | test | 5/5 (100.0%) | 5/5 (100.0%) | 328 | 2.772s ingest + 0.705s search / 22q (`run_metadata_all`) | `$0.000889` ingest + dùng chung `$0.000010` (22q) |
| C | dev | 12/17 (70.6%) | 14/17 (82.4%) | 328 | 0.956s DB upsert + 0.843s search (`run_metadata_dev`) | `$0.0` thêm khi ingest |
| C | test | 5/5 (100.0%) | 5/5 (100.0%) | 328 | 0.376s DB upsert + 0.784s search / 22q (`run_metadata_all`) | `$0.0` thêm + dùng chung `$0.000010` (22q) |

*Ghi chú đo đạc: Lần chạy cuối `run_metadata_all.json` (`2026-11-14T03:28:39Z`, `skip_ingest: false`) ingest lại đủ corpus cho A/B/C và embed chung một batch 22 câu (`4.249s` cho `487` query tokens, `$0.000010`; tổng cả run `94,282` tokens, `$0.001886`). Lần chạy `run_metadata_dev.json` (`03:01:15Z`) đo `17` câu `dev` hết `3.543s` embed query (`379` tokens, `$0.000008`; tổng `$0.001883`).*

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1.00/2 (10 vị trí) | 15/15 (5 test × top-3) | N/A | 0:0 câu, 1:2 câu, 2:3 câu — TB **1.60/2** |
| B | 1.90/2 (10 vị trí) | 15/15 (5 test × top-3) | N/A *(trôi khỏi section đích ở rank 3 `q21`, ranks 2–3 `q22`)* | 0:0 câu, 1:0 câu, 2:5 câu — TB **2.00/2** |
| C | 1.90/2 (10 vị trí) | 15/15 (5 test × top-3) | **2/2** trên `test` (**5/5** tổng `dev`+`test`) | 0:0 câu, 1:0 câu, 2:5 câu — TB **2.00/2** |

*Ghi chú đánh giá Grounding: chỉ số trên chấm mức độ đầy đủ bằng chứng truy xuất của top-3 chunk để trả lời và truy nguồn, **không phải** độ chính xác của câu trả lời sinh ra từ LLM.*

- **Đường dẫn trace, nhãn thủ công, cách chọn mẫu & công cụ hỗ trợ:**
  - Traces & metrics tự động (lưu trực tiếp tại `starter/results/` và đồng bộ sang `results/` ở root): `summary_dev.json`, `summary_all.json`, `traces_dev.json`, `traces_all.json`, `chunk_stats.json`, `ingestion_log.json`, `run_metadata_dev.json`, `run_metadata_all.json`, `artifacts/experiment_log.csv`.
  - Cách chọn mẫu coherence: Chọn trước khi chạy 10 vị trí mở đầu trang cố định (5 trang của `100-1`: pp. 6, 12, 22, 27, 34; 5 trang của `600-1`: pp. 10, 18, 30, 36, 53) phủ đủ văn xuôi, bảng mục lục hàm và bảng Action ID (`results/coherence_samples.json`).
  - Bảng nhãn thủ công: `results/audit_coherence.csv` (30 dòng), `results/audit_metadata.csv` (45 dòng), `results/audit_grounding.csv` (15 dòng, đối chiếu từ `results/test_audit_extract.json`).
  - **Người chấm, thiên lệch & công cụ AI (`GUIDE.md`, `RULES.md`):** Nhãn thủ công được rà soát đối chiếu trực tiếp với văn bản chuẩn hóa gốc và top-3 trace dưới sự hỗ trợ của công cụ AI (Google Antigravity coding agent) để viết code, tạo script kiểm chứng và rà soát đối chiếu. Vì tác giả vừa thiết kế benchmark vừa trực tiếp chấm audit nên có nguy cơ **thiên lệch xác nhận (confirmation bias)**; rủi ro này được giảm bằng cách khóa trước tập test, 10 vị trí coherence và tiêu chí chọn chiến lược trong `benchmark/README.md`, đồng thời ghi trích đoạn cắt cụt/rank lỗi cụ thể trong các tệp CSV để người chấm kiểm tra độc lập.

## Phân tích và kết luận
- **So sánh A–B và B–C; các ví dụ sai có ID câu và nguồn:**
  - **A vs B:** Chunk theo đoạn (`B`) vượt trội rõ rệt so với cắt cứng 500 ký tự (`A`): `Evidence Hit@3` tăng từ `11/17 (64.7%)` lên `13/17 (76.5%)` ở `dev` và từ `2/5 (40.0%)` lên `5/5 (100.0%)` ở `test`; coherence tăng `1.00 -> 1.90/2`; grounding test tăng `1.60 -> 2.00/2`; đồng thời số chunk giảm `41.3%` (`559 -> 328`), giảm chi phí embed (`$0.000987 -> $0.000889`) và thời gian ingest (`8.068s -> 2.772s` ở lần chạy `all`; `7.383s -> 3.785s` ở lần chạy `dev`). Nguyên nhân cốt lõi là A tìm đúng trang (`PageHit@3 = 14/17` dev và `5/5` test), nhưng ranh giới cố định cắt nát bằng chứng:
    - **Ví dụ sai 1 (`A`, câu `q22` — `nist-ai-100-1`, trang 37):** Rank 1 (`nist-ai-100-1:p037:fixed:002`) bắt đầu giữa từ `"ive residual risks..."`, làm rụng nhãn `"MANAGE 1.4: Negative"`; các rank 2–3 (`p.13`, `p.9`) chỉ nói về residual risk chung nên grounding chỉ đạt `1/2` và rớt `Evidence Hit@3`. Tương tự ở câu **`q18` (`nist-ai-100-1`, trang 20)**, rank 2 (`p020:fixed:001`) cắt đứt cụm `"in the face of"`, làm mất phần định nghĩa `"secure"` và `"degrade safely and gracefully"`. (Trên `dev`, `q05` và `q12` cũng trượt `Evidence Hit@3` dù `PageHit@3=True`.)
    - Ngược lại, nhược điểm của B là chunk dài hơn (mean `722.0` ký tự) làm loãng vector khi câu hỏi nhắm vào một câu đơn nằm xen trong bảng dài (vd. `dev q07` trên `100-1` p.34 và `dev q14` trên `600-1` p.53 — nơi A trúng rank 1 còn B trượt top-3).
  - **B vs C:** Giữ nguyên toàn bộ 328 chunk và vector của B (`$0.0` chi phí embed thêm), lọc metadata ở C nâng `dev Evidence Hit@3` từ `13/17 (76.5%)` lên `14/17 (82.4%)` (`Hit@1`: `11/17 -> 12/17`), giữ `5/5 (100%)` ở `test`, đạt tuân thủ filter `5/5` (`3/3 dev + 2/2 test`) và loại bỏ nhiễu chéo section ở tất cả câu có filter (`q15`, `q16`, `q17`, `q21`, `q22`):
    - **Ví dụ sai 2 (`B`, câu `q17` — `nist-ai-600-1`, trang 30, filter `document_type=genai_profile, section=map`):** Không có filter, `B` bị hút bởi từ khóa `"risk"`/`"third-party"` và trôi sang `p.51 appendix` (rank 1) cùng `nist-ai-100-1 pp.45, 44 appendix` (ranks 2–3), trượt hoàn toàn `MP-4.1-008`. Khi bật lọc trong `C`, hệ thống khoanh đúng không gian `map` của `600-1` và đưa `nist-ai-600-1:p030:para:002` lên **rank 1 (`Hit@1=True`)**. Trên `q16` (`dev`), C đẩy gold từ rank 3 lên rank 2; trên `test` (`q21`, `q22`), B bị lọt chunk sai section vào rank 3 (`p.31 map`) và ranks 2–3 (`pp.9/25 foundational`), còn C giữ cả top-3 đúng section đích.
- **Chiến lược chọn, đánh đổi và điều kiện áp dụng:**
  - Theo tiêu chí đã khóa trước trên `dev`, **chọn Chiến lược C** (`by_paragraph=1000` + metadata filter `year`/`document_type`/`section`).
  - **Đánh đổi & điều kiện áp dụng:** Chiến lược C giả định bộ định tuyến/trình hiểu truy vấn trích xuất đúng `year`/`document_type`/`section` và corpus được gán nhãn mục chuẩn. Nếu filter suy đoán sai hoặc quá hẹp, `SQL WHERE` cứng có thể loại nhầm chunk đúng; do đó khi triển khai thực tế nên chỉ bật lọc cứng cho phạm vi chắc chắn và fallback sang truy xuất không lọc (như B) nếu kết quả lọc rỗng hoặc độ tin cậy thấp.
- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**
  - Tập `test` chỉ gồm 5 câu nên cả B và C cùng đạt trần `5/5`, chưa thể hiện hết chênh lệch bằng chỉ số tự động mà phải dựa thêm vào `dev` (`q15`–`q17`) và `audit_metadata.csv` (`q21`, `q22`); không nên suy rộng kết luận cho toàn bộ các loại tài liệu ngoài corpus NIST.
  - Mẫu coherence cố định 10 vị trí mở đầu trang (`chunk 000`) chỉ ra điểm gãy page-break ở `600-1` p.53 (`1/2`), nhưng chưa kiểm tra toàn bộ 328 chunk giữa trang.
  - Thời gian `search_seconds` trong `run_metadata_all.json` được đo gộp cho toàn batch 22 câu (`dev + test`), còn `embed_seconds` chịu biến động độ trễ mạng API giữa các lần chạy (vd. ingest B mất `3.785s` ở lần `dev` và `2.772s` ở lần `all`); ngoài ra chưa đánh giá độ chính xác câu trả lời LLM đầu cuối do scope bài dừng ở retrieval grounding.
- **Nếu làm lại hoặc mở rộng, cải tiến gì?**
  1. Nối câu vắt qua ranh giới trang vật lý trước khi chia đoạn để xử lý dứt điểm lỗi cắt đầu trang như `nist-ai-600-1` p.52→p.53.
  2. Tách các bảng hành động NIST theo từng đơn vị `Action ID` (`GV-x`, `MP-x`, `MS-x`, `MG-x`) kèm tiêu đề subcategory cha (parent-child chunking) để vừa giữ trọn cấu trúc, vừa khắc phục loãng ngữ nghĩa như `q07`, `q14`.
  3. Thử nghiệm tìm kiếm lai **BM25 + pgvector cosine (`RRF`)** để bắt chính xác mã hiệu điều khoản/từ khóa kỹ thuật hiếm gặp trên nền tập test mở rộng ≥15–20 câu.
