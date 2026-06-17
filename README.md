# ZaloPay Home Analytics Agent

## 1. Tổng quan

ZaloPay Home Analytics Agent là một AI Agent được xây dựng để hỗ trợ phân tích performance của ZaloPay Home. Agent giúp các team Product, Data, BA và Growth đặt câu hỏi bằng ngôn ngữ tự nhiên, tự động chạy phân tích trên bộ dữ liệu Home event log và payment đã được anonymized, sau đó trả về bảng số liệu, insight và đề xuất hành động theo góc nhìn product.

Giải pháp này không chỉ dừng ở việc hỏi đáp số liệu, mà hướng đến một workflow báo cáo gần như end-to-end:

```text
Natural language question
→ Metric logic mapping
→ Data query & analysis
→ Structured KPI report
→ Product insight
→ PDF export
→ Email delivery
→ Scheduled recurring report
```

Thay vì phải viết SQL/Python thủ công, copy kết quả, format report, xuất file và gửi email, user có thể hỏi agent để tạo báo cáo Home performance và gửi report cho các thành viên trong team.

---

## 2. Bài toán cần giải quyết

Trong công việc thực tế, team Product/Data thường xuyên cần theo dõi các chỉ số Home performance như:

- Home Load Users
- Interaction Rate
- Conversion Rate
- Retention Rate
- Open App Frequency
- Component Click Rate
- Service/App Click Rate
- Breakdown theo tháng, OS, app version, user segment hoặc component

Quy trình hiện tại thường gồm nhiều bước thủ công:

- Xác định metric cần tính.
- Define numerator và denominator.
- Viết SQL/Python query.
- Chạy số liệu theo ngày/tháng.
- Kiểm tra logic và validate kết quả.
- Tổng hợp insight.
- Format report.
- Export file.
- Gửi email cho các thành viên trong team.
- Lặp lại workflow này theo tuần hoặc theo tháng.

Điều này tạo ra một số pain point:

- Product Owner hoặc Business Analyst phụ thuộc nhiều vào Data Analyst để lấy số.
- Data Analyst mất thời gian cho các report lặp lại thay vì tập trung vào phân tích sâu.
- Metric logic dễ bị lệch giữa các lần phân tích nếu không được chuẩn hóa.
- Các câu hỏi follow-up mất thêm thời gian vì cần chỉnh query thủ công.
- Việc format report, export file và gửi email tạo thêm operational effort.
- Stakeholders không phải lúc nào cũng nhận được report đúng lịch nếu quy trình còn thủ công.

Home Performance Analytics Agent được xây dựng để giảm các effort này bằng cách chuyển câu hỏi tự nhiên của user thành phân tích dữ liệu có cấu trúc, có metric logic rõ ràng và có thể tự động hóa bước gửi báo cáo.

---

## 3. Người dùng mục tiêu

| Nhóm user | Nhu cầu chính |
|---|---|
| Product Owner | Theo dõi Home performance, phát hiện vấn đề và tìm product opportunity |
| Business Analyst | Chuẩn bị báo cáo định kỳ và tổng hợp insight |
| Data Analyst | Chuẩn hóa metric logic và giảm các query/report lặp lại |
| Growth team | Phân tích engagement, conversion và user segment |
| Stakeholders/Managers | Nhận báo cáo performance định kỳ qua email/PDF |

---

## 4. Agent có thể làm gì?

Agent hỗ trợ các nhóm capability chính:

- Hiểu câu hỏi Home performance bằng ngôn ngữ tự nhiên.
- Tự động mapping câu hỏi sang metric logic phù hợp.
- Define numerator/denominator trước khi tính toán.
- Query dữ liệu event log và payment đã được anonymized.
- Trả về bảng số liệu theo tháng/ngày/component/segment.
- Phân tích nguyên nhân thay đổi KPI bằng cách breakdown numerator và denominator.
- Deep-dive theo Home component, OS, app version hoặc nhóm user.
- Gợi ý Product Opportunity dựa trên pattern trong dữ liệu.
- Xuất report thành file PDF.
- Gửi report qua email cho các thành viên trong team.
- Có thể schedule gửi báo cáo định kỳ theo tuần hoặc theo tháng.

Agent được tối ưu cho bài toán Home product analytics, không phải một chatbot generic.

---

## 5. Dataset

Demo sử dụng bộ dữ liệu đã được anonymized từ Home event log và payment transaction.

### 5.1 Bảng `event_log`

Bảng `event_log` chứa dữ liệu hành vi của user trên Home.

Thời gian dữ liệu:

```text
Tháng 03/2026 đến tháng 05/2026
```

Các cột chính:

| Column | Ý nghĩa |
|---|---|
| `ymd` | Ngày phát sinh event, format YYYYMMDD |
| `timestamp` | Thời điểm phát sinh event |
| `user_id` | User ID đã được anonymized |
| `event_id` | Home event ID đã được mask |
| `os` | Operating system |
| `appver` | App version |
| `app_profile_id` | ID của service/app profile |
| `app_profile_name` | Tên service/app profile |
| `metadata` | Event metadata đã được làm sạch |
| `session_id` | Session ID |

Một số event quan trọng:

| Event ID | Ý nghĩa |
|---|---|
| `AAAA.005` | Load Home Page |
| `AAAA.007` | Click nav bar |
| `AAAA.010` | Click notification |
| `AAAA.011` | Click search bar |
| `AAAA.012` | Click balance block |
| `AAAA.019` | Click shortcut |
| `AAAA.020` | Click specific service icon |
| `AAAA.029` | Click voucher |
| `AAAA.031` | Click hero card |
| `AAAA.032` | Click group service |
| `AAAA.033` | Click dynamic card |
| `AAAA.034` | Click dynamic card detail |
| `AAAA.041` | View floating icon |
| `AAAA.042` | Click floating icon |
| `AAAA.048` | Click scroll-to-top |

### 5.2 Bảng `payment`

Bảng `payment` chứa các giao dịch payment thành công của nhóm user đã được anonymized.

Các cột chính:

| Column | Ý nghĩa |
|---|---|
| `payment_ymd` | Ngày phát sinh payment |
| `user_id` | User ID đã được anonymized |
| `payment_time` | Thời điểm phát sinh payment |
| `trans_id` | Transaction ID |
| `app_id` | Payment app ID |
| `amount` | Giá trị giao dịch |
| `trans_type` | Transaction type |

Logic payment:

```text
Successful payment = transStatus = 1
```

---

## 6. Metric Definition chính

### 6.1 Home Load Users

Số lượng distinct users có load Home.

```text
Home Load Users = COUNT(DISTINCT user_id)
WHERE event_id = 'AAAA.005'
```

### 6.2 Interaction Rate

Tỷ lệ Home users có phát sinh ít nhất một interaction chủ động trên Home.

```text
Interaction Rate = Interaction Users / Home Load Users
```

Logic:

- Denominator: users có `AAAA.005` Load Home.
- Numerator: users có Load Home và có ít nhất một explicit interaction event.
- Không tính các event chỉ mang tính view/impression như `AAAA.041` là proactive interaction.

### 6.3 Home-to-Payment Conversion Rate

Tỷ lệ Home users có phát sinh ít nhất một successful payment trong cùng kỳ phân tích.

```text
Home-to-Payment Conversion Rate = Payment Users / Home Load Users
```

Lưu ý:

- Đây là conversion ở anonymized-user level.
- Không enforce strict same-session funnel hoặc payment xảy ra ngay sau Home load.

### 6.4 Retention Rate

Với new user, retention có thể được tính bằng cách kiểm tra user có quay lại Home sau lần access đầu tiên hay không.

Ví dụ logic monthly:

```text
New User Retention Rate = New users quay lại Home sau first access / New users đã access Home
```

Tùy độ chi tiết dữ liệu, retention có thể được xem theo D+1, D+7 hoặc monthly return behavior.

### 6.5 Open App by Number of Days

User được chia nhóm theo số ngày active Home trong tháng.

Các bucket đề xuất:

```text
1 ngày
2 ngày
3 ngày
4–5 ngày
6–10 ngày
11–15 ngày
16–20 ngày
>20 ngày
```

Metric này giúp phân loại user thành nhóm low-frequency, medium-frequency và high-frequency để tìm opportunity cải thiện engagement hoặc retention.

---

## 7. Demo Use Cases

### Case 1 — Monthly Home KPI Report

Mục tiêu: tạo báo cáo Home KPI định kỳ cho tháng 3, tháng 4 và tháng 5.

Prompt demo:

```text
Phân tích tổng quan số liệu có trong bảng event log.
Home KPI gồm các metric sau:
1. Interaction rate: view toàn tháng và view trung bình theo ngày
2. Conversion rate cho new user
3. Retention rate cho new user
4. Open app by number of days: 1 ngày, 2 ngày, 3 ngày,... >10, >15, >20 ngày

Giúp tôi define metric & logic để tính và report các chỉ số này cho tháng 3, tháng 4, tháng 5.
Sau đó chạy query để lấy số liệu thực tế cho 3 tháng này.
```

Output kỳ vọng:

- Định nghĩa metric.
- Logic tính toán.
- Bảng KPI theo tháng.
- Nhận xét ngắn về trend.
- Caveat nếu dữ liệu chưa đủ để tính một metric nào đó.

Giá trị business:

Case này cho thấy agent có thể tự động hóa báo cáo Home KPI định kỳ, giúp giảm effort viết query và tổng hợp số liệu thủ công.

### Case 2 — KPI Deep-dive & Driver Diagnosis

Mục tiêu: phân tích nguyên nhân thay đổi của Interaction Rate giữa các tháng.

Prompt demo:

```text
Interaction rate tháng 5 thay đổi như thế nào so với tháng 4?
Phân tích giúp tôi nguyên nhân thay đổi đến từ Home users hay Interaction users.
Sau đó breakdown theo Home component để xem component nào đóng góp nhiều nhất vào thay đổi.
```

Output kỳ vọng:

- So sánh Month-over-Month.
- Breakdown numerator/denominator.
- Breakdown theo Home component.
- Insight về component hoặc hành vi user đang góp phần kéo KPI tăng/giảm.

Follow-up có thể demo:

```text
Breakdown thêm theo OS đi.
```

```text
Chỉ show data thôi.
```

Giá trị business:

Case này chứng minh agent không chỉ trả số, mà còn hỗ trợ Product team deep-dive nguyên nhân thay đổi KPI.

### Case 3 — Product Opportunity by Open App Frequency

Mục tiêu: xác định nhóm user nào đang có opportunity lớn nhất để cải thiện engagement trên Home.

Prompt demo:

```text
Phân tích Home users theo nhóm tần suất mở app trong tháng 3, 4, 5: 
1 ngày, 2 ngày, 3 ngày, 4–5 ngày, 6–10 ngày, 11–15 ngày, 16–20 ngày và >20 ngày.

Với mỗi nhóm, tính Home users, interaction rate và Home-to-Payment conversion rate.
Sau đó chỉ ra nhóm user nào có cơ hội product lớn nhất để cải thiện engagement, kèm 3 đề xuất hành động cho team Home.
```

Output kỳ vọng:

- Segment user theo open app frequency.
- Interaction Rate và Conversion Rate của từng nhóm.
- Xác định nhóm user có product opportunity lớn nhất.
- Đề xuất hướng hành động cụ thể cho team Home.

Giá trị business:

Case này giúp team chuyển từ việc chỉ tracking metric sang tìm action. Agent có thể chỉ ra nhóm user nên ưu tiên để activation, engagement hoặc retention.

---

## 8. PDF Export, Email Delivery & Scheduled Reports

Ngoài phần phân tích dữ liệu, team đã set up thêm workflow tự động để phân phối report.

Sau khi Analytics Agent tạo Home Performance Report, output có thể được format, xuất thành file PDF và gửi email cho các thành viên trong team.

Workflow hiện tại:

```text
Analytics Agent generates report
→ Report output is formatted
→ PDF report is generated
→ Email is composed
→ PDF is attached
→ Email is sent to selected team members
```

Luồng này giúp biến agent từ một công cụ hỏi đáp on-demand thành một reporting automation workflow thực tế.

Các use case hỗ trợ:

| Use case | Mô tả |
|---|---|
| Send report now | Generate Home Performance Report, export thành PDF và gửi email cho team |
| Weekly report | Tự động gửi Home performance report hằng tuần |
| Monthly report | Tự động gửi monthly KPI performance summary |
| Reduce manual reporting effort | Giảm thao tác thủ công như chạy query, format report, export PDF và gửi email |

Prompt ví dụ:

```text
Gửi report này qua email cho team Home.
```

```text
Xuất report này thành PDF và gửi cho các thành viên trong team.
```

```text
Schedule gửi Home Performance Report mỗi thứ Hai lúc 9h sáng.
```

Giá trị business:

Luồng Email Delivery và Scheduler giúp giảm effort cho việc chạy và report data performance định kỳ. Stakeholders có thể nhận báo cáo đúng lịch mà không cần có người chạy lại query, xuất file và gửi email thủ công mỗi lần.

---

## 9. Response Design

Output của agent được thiết kế để dễ đọc trong chat UI.

Format mặc định:

```text
Short answer
→ Table
→ Key insights
→ Caveat nếu cần
```

Agent không show SQL/Python mặc định. Chỉ khi user yêu cầu thì mới hiển thị query hoặc logic chi tiết.

Ví dụ:

```text
Show me the query.
```

```text
Giải thích logic tính metric này.
```

Nếu user yêu cầu data-only output, agent chỉ trả bảng.

Ví dụ:

```text
Chỉ show data thôi.
```

```text
Không cần giải thích.
```

---

## 10. System Architecture

High-level architecture:

```text
Frontend Chat UI
→ Backend API
→ AgentBase Runtime
→ Analytics Agent
→ Data Query Layer
→ Formatted Response
```

Với report delivery extension:

```text
Analytics Agent
→ PDF Export
→ Email Delivery Agent
→ Scheduler
→ Team Members
```

Các component chính:

| Component | Vai trò |
|---|---|
| Frontend UI | Chat interface, suggested prompts, file upload, table rendering |
| Analytics Agent | Hiểu intent, mapping metric logic, query data, generate insight |
| Data Layer | Lưu và query anonymized event/payment data |
| PDF Export | Convert generated report thành PDF file |
| Email Delivery Agent | Compose và gửi report email cho team members |
| Scheduler | Trigger recurring report generation và delivery |

---

## 11. Limitations

- Dataset hiện tại là anonymized và sampled cho mục đích demo.
- Payment conversion được tính ở anonymized-user level, chưa phải strict same-session funnel.
- Một số metric như strict retention hoặc NPU conversion cần thêm data hoặc cohort definition rõ hơn.
- Nếu phân tích conversion theo từng service icon, cần mapping rõ giữa Home event `app_profile_id` và payment `app_id`.
- Agent được tối ưu cho Home performance analytics, chưa cover toàn bộ domain của ZaloPay.

---

## 12. Future Improvements

Các hướng phát triển tiếp theo:

- Bổ sung cohort retention analysis chi tiết hơn.
- Bổ sung NPU-specific funnel và conversion logic.
- Xây dựng strict time-to-payment funnel sau Home load.
- Thêm chart visualization cho trend theo tháng.
- Cho phép download output dưới dạng CSV/Excel.
- Cải thiện template PDF report.
- Quản lý recipient list linh hoạt hơn.
- Hỗ trợ schedule gửi report theo ngày/tuần/tháng.
- Thêm anomaly detection cho các biến động KPI bất thường.
- Xây dựng thêm report template cho Product và Management stakeholders.

---

## 13. Repository Structure

Cấu trúc repo đề xuất:

```text
.
├── README.md
├── index.html
├── system_prompt_home_performance_agent.md
├── data/
│   ├── event_log.*
│   └── payment.*
├── app/
│   ├── analytics_agent/
│   ├── email_agent/
│   └── services/
└── assets/
```

Các file chính:

| File | Mô tả |
|---|---|
| `README.md` | Tài liệu mô tả project |
| `index.html` | Frontend chat UI |
| `system_prompt_home_performance_agent.md` | Prompt và metric behavior rules của agent |
| `event_log` | Dữ liệu Home event đã anonymized |
| `payment` | Dữ liệu successful payment đã anonymized |
| `email_agent` | Luồng email delivery và scheduled report |

---

## 14. Demo Storyline

Flow video demo đề xuất:

1. Giới thiệu pain point: Home KPI report cần viết query, format kết quả và gửi report thủ công.
2. Demo Case 1: Generate Monthly Home KPI Report cho tháng 3, tháng 4 và tháng 5.
3. Demo Case 2: Hỏi agent vì sao Interaction Rate thay đổi và breakdown theo component.
4. Demo Case 3: Phân tích Product Opportunity theo nhóm tần suất mở app.
5. Show delivery workflow: export report thành PDF và gửi email cho team members.
6. Nhắc đến scheduled delivery: report có thể được gửi tự động theo tuần hoặc tháng.
7. Kết luận value: faster reporting, standardized metric logic, better product insight và automated report distribution.
