# Hệ thống khảo sát hài lòng người bệnh

Ứng dụng khảo sát theo biểu mẫu Bộ Y tế, gồm:

- **Mẫu số 1:** người bệnh nội trú (`/`)
- **Mẫu số 2:** người bệnh ngoại trú (`/mau-2`)
- **Trang quản trị:** xem, chỉnh sửa, duyệt và gửi phiếu (`/staff`)

## Luồng xử lý

1. Người bệnh hoàn tất phiếu khảo sát.
2. Máy chủ lưu phiếu ở trạng thái **chờ kiểm duyệt**.
3. Quản trị viên kiểm tra hoặc chỉnh sửa nội dung, sau đó duyệt.
4. Quản trị viên bấm **Gửi BYT** để máy chủ đăng nhập cổng BYT và gửi phiếu theo Mẫu số tương ứng.

## Chạy ứng dụng

```powershell
python app.py
```

Để phục vụ qua mạng nội bộ cần chứng thư TLS:

```powershell
python app.py --host 0.0.0.0 --port 8765 --cert cert.pem --key key.pem
```

## Quản trị và cấu hình

Tạo hoặc đặt lại tài khoản quản trị:

```powershell
python staff_auth.py add <ten-dang-nhap>
```

Cấu hình tài khoản đồng bộ BYT trên máy chủ:

```powershell
python configure_byt.py
```

Dữ liệu khảo sát, tài khoản quản trị, cấu hình BYT và chứng thư TLS nằm trong các đường dẫn đã được `.gitignore`; không được đưa lên GitHub.
