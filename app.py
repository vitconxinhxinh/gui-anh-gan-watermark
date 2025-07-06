import os
import io
import base64
import time
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from Crypto.Random import get_random_bytes
from Crypto.PublicKey import RSA
from models import db, User, Message
from crypto_utils import *
from models import db, User, Message, Handshake  # Thêm Handshake vào đây
from flask import Flask, abort  # Thêm abort vào đây
from flask import send_file, abort, request


UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# --- LOGIN MANAGER ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# --- HOME & AUTH ---
@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if User.query.filter_by(username=username).first():
            flash("Tên đăng nhập đã tồn tại!")
            return redirect(url_for("register"))
        pw_hash = generate_password_hash(password)
        user = User(username=username, password_hash=pw_hash)
        db.session.add(user)
        db.session.commit()
        flash("Đăng ký thành công, đăng nhập ngay!")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash("Sai thông tin đăng nhập!")
            return redirect(url_for("login"))
        login_user(user)
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))

# --- DASHBOARD, TẠO KEY ---
@app.route("/dashboard")
@login_required
def dashboard():
    users = User.query.filter(User.id != current_user.id).all()
    new_requests = Handshake.query.filter_by(receiver_id=current_user.id, status='pending').count()
    return render_template("dashboard.html", users=users, new_requests=new_requests)

@app.route("/create_key", methods=["GET", "POST"])
@login_required
def create_key():
    if request.method == "POST":
        key = RSA.generate(2048)
        priv_pem = key.export_key()
        pub_pem = key.publickey().export_key()
        current_user.private_key = priv_pem
        current_user.public_key = pub_pem
        db.session.commit()
        flash("Đã tạo cặp khóa RSA mới!")
        return redirect(url_for("dashboard"))
    return render_template("create_key.html")

@app.route("/download_public_key")
@login_required
def download_public_key():
    if not current_user.public_key:
        flash("Bạn chưa tạo public key!")
        return redirect(url_for("dashboard"))
    return send_file(
        io.BytesIO(current_user.public_key),
        mimetype='application/x-pem-file',
        as_attachment=True,
        download_name=f"{current_user.username}_public.pem"
    )

@app.route("/download_private_key")
@login_required
def download_private_key():
    if not current_user.private_key:
        flash("Bạn chưa tạo private key!")
        return redirect(url_for("dashboard"))
    return send_file(
        io.BytesIO(current_user.private_key),
        mimetype='application/x-pem-file',
        as_attachment=True,
        download_name=f"{current_user.username}_private.pem"
    )

# --- CHAT, GỬI FILE ---
@app.route("/chat/<int:user_id>", methods=["GET", "POST"])
@login_required
def chat(user_id):
    other = User.query.get_or_404(user_id)
    
    if request.method == "POST":
        msg = request.form.get("text", "").strip()
        file = request.files.get("file")
        is_key = False
        is_packet = False
        file_path = file_name = file_display_name = None
        
        try:
            # Xử lý file đính kèm (nếu có)
            if file and file.filename:
                # Kiểm tra kích thước file (tối đa 10MB)
                if file.content_length > 10 * 1024 * 1024:
                    flash("File quá lớn (tối đa 10MB)", "error")
                    return redirect(url_for("chat", user_id=user_id))
                
                # Chuẩn hóa tên file
                original_name = file.filename
                safe_name = secure_filename(original_name)
                timestamp = int(time.time())
                stored_filename = f"{timestamp}_{safe_name}"
                
                # Tạo đường dẫn đầy đủ
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)
                
                # Đảm bảo thư mục tồn tại
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                
                # Đọc nội dung file
                file_data = file.read()
                
                # Kiểm tra loại file
                if file.filename.lower().endswith(".pem"):
                    is_key = True
                elif file.filename.lower().endswith(".json"):
                    is_packet = True
                else:
                    # Kiểm tra magic number chỉ cho file ảnh
                    if not file_data.startswith(b'\x89PNG') and not file_data.startswith(b'\xFF\xD8'):
                        flash("Chỉ chấp nhận file ảnh PNG/JPG/JPEG hoặc file packet JSON", "error")
                        return redirect(url_for("chat", user_id=user_id))
                
                # Lưu file
                with open(file_path, 'wb') as f:
                    f.write(file_data)
                
                if not os.path.exists(file_path):
                    raise IOError("Không thể lưu file")
                
                # Cập nhật thông tin file
                file_name = stored_filename
                file_display_name = original_name

            # Tạo message mới
            message = Message(
                sender_id=current_user.id,
                receiver_id=other.id,
                text=msg if msg else None,
                file_name=file_name,
                file_display_name=file_display_name,
                is_key=is_key,
                is_packet=is_packet
            )
            
            db.session.add(message)
            db.session.commit()
            flash("Tin nhắn đã được gửi thành công", "success")

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Lỗi khi gửi tin nhắn: {str(e)}")
            flash(f"Có lỗi xảy ra: {str(e)}", "error")
        
        return redirect(url_for("chat", user_id=user_id))

    # Lấy danh sách tin nhắn
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.created_at.asc()).all()
    
    return render_template("chat.html", 
                         other=other, 
                         messages=messages)


@app.route("/initiate_handshake/<int:user_id>")
@login_required
def initiate_handshake(user_id):
    other = User.query.get_or_404(user_id)
    # Tìm handshake bất kể trạng thái nào
    hs = Handshake.query.filter(
        Handshake.sender_id == current_user.id,
        Handshake.receiver_id == user_id
    ).order_by(Handshake.created_at.desc()).first()

    if not hs:
        hs = Handshake(sender_id=current_user.id, receiver_id=user_id)
        db.session.add(hs)
        db.session.commit()
        status = "pending"
    else:
        status = hs.status

    return render_template("handshake.html", other=other, status=status)


@app.route("/pending_handshakes")
@login_required
def pending_handshakes():
    # Lấy các yêu cầu handshake đang chờ
    pending = Handshake.query.filter(
        Handshake.receiver_id == current_user.id,
        Handshake.status == 'pending'
    ).all()
    
    # Chuẩn bị danh sách mới với thông tin username
    pending_info = []
    for hs in pending:
        sender = User.query.get(hs.sender_id)
        pending_info.append({
            'id': hs.id,
            'sender_username': sender.username if sender else 'Unknown',
        })

    return render_template("pending_handshakes.html", pending=pending_info)


@app.route("/accept_handshake/<int:hs_id>")
@login_required
def accept_handshake(hs_id):
    hs = Handshake.query.get_or_404(hs_id)
    if hs.receiver_id != current_user.id:
        abort(403)
    
    hs.status = 'accepted'
    db.session.commit()
    
    # Tạo thông báo cho người gửi
    notification = Message(
        sender_id=current_user.id,
        receiver_id=hs.sender_id,
        text=f"{current_user.username} đã chấp nhận kết nối",
        is_ack=True
    )
    db.session.add(notification)
    db.session.commit()
    
    flash("Đã chấp nhận yêu cầu kết nối")
    return redirect(url_for('pending_handshakes'))

@app.route("/reject_handshake/<int:hs_id>")
@login_required
def reject_handshake(hs_id):
    hs = Handshake.query.get_or_404(hs_id)
    if hs.receiver_id != current_user.id:
        abort(403)
    
    hs.status = 'rejected'
    db.session.commit()
    
    # Tạo thông báo cho người gửi
    notification = Message(
        sender_id=current_user.id,
        receiver_id=hs.sender_id,
        text=f"{current_user.username} đã từ chối kết nối",
        is_nack=True
    )
    db.session.add(notification)
    db.session.commit()
    
    flash("Đã từ chối yêu cầu kết nối")
    return redirect(url_for('pending_handshakes'))


# --- GỬI FILE BẢO MẬT ---
@app.route("/send_packet/<int:user_id>", methods=["GET", "POST"])
@login_required
def send_packet(user_id):
    other = User.query.get_or_404(user_id)
    # Kiểm tra handshake
    hs = Handshake.query.filter(
        Handshake.sender_id == current_user.id,
        Handshake.receiver_id == user_id,
        Handshake.status == 'accepted'
    ).first()
    if not hs:
        flash("Bạn cần thực hiện handshake trước khi gửi packet")
        return redirect(url_for('initiate_handshake', user_id=user_id))

    if request.method == "POST":
        try:
            # 1. Validate input
            if 'photo' not in request.files or not request.files['photo']:
                flash("Vui lòng chọn file ảnh")
                return redirect(request.url)
                
            photo = request.files['photo']
            if not photo or photo.filename == '':
                flash("Vui lòng chọn file ảnh hợp lệ")
                return redirect(request.url)

            # Kiểm tra định dạng file
            if not photo.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                flash("Chỉ chấp nhận file ảnh PNG/JPG/JPEG")
                return redirect(request.url)

            # Đọc dữ liệu ảnh trước khi xử lý
            img_data = photo.read()
            photo.seek(0)  # Reset file pointer để save lại sau
            
            # Kiểm tra magic number
            if not (img_data.startswith(b'\xFF\xD8') and not img_data.startswith(b'\x89PNG')):
                flash("File không phải ảnh hợp lệ")
                return redirect(request.url)

            watermark = request.form.get('watermark', 'Protected').strip()
            pubkey_file = request.files.get('public_key')
            des_key_str = request.form.get('des_key', '').strip()

            if not pubkey_file and not des_key_str:
                flash("Bạn phải upload public key của người nhận hoặc nhập DES key tay")
                return redirect(request.url)

            # 2. Lưu file gốc
            real_filename = f"{int(time.time())}_{secure_filename(photo.filename)}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], real_filename)
            photo.save(filepath)

            # 3. Tạo watermark nếu có
            watermark_file = None
            if watermark:
                watermarked_filename = f"wm_{real_filename}"
                watermarked_path = os.path.join(app.config['UPLOAD_FOLDER'], watermarked_filename)
                add_watermark(filepath, watermark, watermarked_path)
                watermark_file = watermarked_filename
                with open(filepath, 'rb') as f:
                    img_data = f.read()  

            # 4. Tạo session key
            session_key = None
            session_key_for_packet = None
            if des_key_str:
                session_key = make_des_key(des_key_str.encode('utf-8'))
                if len(session_key) != 8:
                    flash("DES key phải có đúng 8 ký tự")
                    return redirect(request.url)
                session_key_for_packet = base64.b64encode(session_key).decode()
            else:
                pubkey_bytes = pubkey_file.read()
                try:
                    RSA.import_key(pubkey_bytes)  # Validate public key
                except Exception as e:
                    flash(f"Public key không hợp lệ: {str(e)}")
                    return redirect(request.url)
                
                session_key = get_random_bytes(8)
                enc_session_key = encrypt_session_key(session_key, pubkey_bytes)
                session_key_for_packet = enc_session_key.decode()

            # 5. Mã hóa ảnh
            iv = get_random_bytes(8)
            cipher = encrypt_des(img_data, session_key, iv)

            # 6. Tạo metadata và hash
            expiration = int(time.time()) + 3600  # 1 giờ
            metadata = {
                'filename': photo.filename,
                'timestamp': int(time.time()),
                'watermark': watermark,
                'sender': current_user.username,
                'expiration': expiration,
                'file_size': len(img_data)
            }
            meta_bytes = json.dumps(metadata).encode()
            hash_value = sha512_hash(iv + cipher + str(expiration).encode())

            # 7. Tạo chữ ký
            sender_privkey_file = request.files.get('sender_private_key')
            if not sender_privkey_file:
                flash("Vui lòng upload private key của bạn")
                return redirect(request.url)
                
            try:
                sender_privkey_bytes = sender_privkey_file.read()
                sig = sign_data(meta_bytes, sender_privkey_bytes)
            except Exception as e:
                flash(f"Lỗi tạo chữ ký: {str(e)}")
                return redirect(request.url)

            # 8. Tạo và lưu packet
            packet_data = {
                "metadata": base64.b64encode(meta_bytes).decode(),
                "sig": sig.decode(),
                "session_key": session_key_for_packet,
                "manual_des_key": bool(des_key_str),
                "iv": base64.b64encode(iv).decode(),
                "cipher": base64.b64encode(cipher).decode(),
                "hash": hash_value
            }

            packet_filename = f"packet_{int(time.time())}.json"
            packet_path = os.path.join(app.config['UPLOAD_FOLDER'], packet_filename)
            with open(packet_path, "w") as f:
                json.dump(packet_data, f, indent=2)

            # 9. Lưu message
            message = Message(
                sender_id=current_user.id,
                receiver_id=other.id,
                text=f"(Packet bảo mật) {photo.filename}",
                file_name=packet_filename,
                file_display_name=photo.filename,
                is_packet=True
            )
            db.session.add(message)
            db.session.commit()

            flash("Đã gửi packet bảo mật thành công!")
            return render_template(
                "send_packet.html",
                other=other,
                watermark_file=watermark_file,
                packet_file=packet_filename 
            )

        except Exception as e:
            db.session.rollback()
            flash(f"Có lỗi xảy ra: {str(e)}")
            app.logger.error(f"Error in send_packet: {str(e)}")
            return redirect(request.url)

    return render_template("send_packet.html", other=other)

@app.template_filter('format_datetime')
def format_datetime_filter(value, format='%H:%M %d/%m/%Y'):
    if value is None:
        return ""
    if isinstance(value, int):
        return datetime.fromtimestamp(value).strftime(format)
    return value.strftime(format)

@app.template_filter('format_file_size')
def format_file_size_filter(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} GB"


# --- NHẬN/GIẢI MÃ FILE BẢO MẬT ---
@app.route("/decrypt_packet/<int:msg_id>", methods=["GET", "POST"])
@login_required
def decrypt_packet(msg_id):
    msg = Message.query.get_or_404(msg_id)
    steps = []
    decrypted_file = None

    # Kiểm tra quyền truy cập
    if msg.receiver_id != current_user.id or not msg.is_packet:
        steps.append("❌ Bạn không có quyền giải mã packet này!")
        return render_template("decrypt_packet.html", msg=msg, steps=steps)

    if request.method == "POST":
        try:
            des_key_str = request.form.get('des_key', '').strip()
            session_key = None

            # 1. Đọc và validate packet
            if not msg.file_name:
                flash("Không tìm thấy file packet", "error")
                return redirect(url_for('chat', user_id=msg.sender_id))
            
            packet_path = os.path.join(app.config['UPLOAD_FOLDER'], msg.file_name)
            
            with open(packet_path, "r") as f:
                packet = json.load(f)

            # 2. Giải mã metadata
            meta_bytes = base64.b64decode(packet['metadata'])
            metadata = json.loads(meta_bytes.decode())
            current_time = int(time.time())

            # 3. Kiểm tra hạn dùng
            if current_time > metadata.get('expiration', current_time + 1):
                steps.append("❌ Hạn sử dụng: Đã hết hạn!")
                return render_template("decrypt_packet.html", msg=msg, steps=steps)
            steps.append("✅ Hạn sử dụng: Còn hiệu lực")

            # 4. Kiểm tra hash toàn vẹn
            iv = base64.b64decode(packet['iv'])
            cipher = base64.b64decode(packet['cipher'])
            expiration_bytes = str(metadata['expiration']).encode()
            valid_hash = sha512_hash(iv + cipher + expiration_bytes)
            
            if valid_hash != packet['hash']:
                steps.append("❌ Kiểm tra toàn vẹn: Hash không khớp (dữ liệu bị thay đổi!)")
                return render_template("decrypt_packet.html", msg=msg, steps=steps)
            steps.append("✅ Kiểm tra toàn vẹn: Hash khớp (dữ liệu nguyên vẹn)")

            # 5. Lấy session key
            if packet.get('manual_des_key') and des_key_str:
                session_key = make_des_key(des_key_str.encode('utf-8'))
                if len(session_key) != 8:
                    steps.append("❗ DES key phải đúng 8 ký tự/byte")
                    return render_template("decrypt_packet.html", msg=msg, steps=steps)
                steps.append(f"✅ Đã sử dụng DES key nhập tay")
            else:
                if 'private_key' not in request.files:
                    steps.append("❌ Vui lòng upload private key")
                    return render_template("decrypt_packet.html", msg=msg, steps=steps)
                
                privkey_file = request.files['private_key']
                privkey_bytes = privkey_file.read()
                
                try:
                    session_key = decrypt_session_key(packet['session_key'], privkey_bytes)
                    steps.append("✅ Giải mã session key thành công")
                except Exception as ex:
                    steps.append(f"❌ Giải mã session key thất bại: {ex}")
                    return render_template("decrypt_packet.html", msg=msg, steps=steps)

            # 6. Kiểm tra chữ ký số
            sender_pubkey_file = request.files.get('sender_public_key')
            if not sender_pubkey_file:
                steps.append("❌ Vui lòng upload public key của người gửi")
                return render_template("decrypt_packet.html", msg=msg, steps=steps)
            
            sender_pubkey_bytes = sender_pubkey_file.read()
            
            if not verify_signature(meta_bytes, packet['sig'], sender_pubkey_bytes):
                steps.append("❌ Chữ ký: Không hợp lệ!")
                return render_template("decrypt_packet.html", msg=msg, steps=steps)
            steps.append("✅ Chữ ký: Hợp lệ!")

            # 7. Giải mã ảnh
            try:
                img_data = decrypt_des(cipher, session_key, iv)
            except Exception as err:
                nack_msg = Message(
                    sender_id=current_user.id,
                    receiver_id=msg.sender_id,
                    text=f"NACK: Giải mã thất bại file {metadata['filename']}",
                    is_nack=True
                )
                db.session.add(nack_msg)
                db.session.commit()
                
                steps.append(f"❌ Lỗi giải mã: {err}")
                steps.append("❗ Gợi ý: Key giải mã có thể không đúng")
                return render_template("decrypt_packet.html", msg=msg, steps=steps)

            # 8. Kiểm tra định dạng ảnh
            if not (img_data.startswith(b'\xFF\xD8') and not img_data.startswith(b'\x89PNG')):
                nack_msg = Message(
                    sender_id=current_user.id,
                    receiver_id=msg.sender_id,
                    text=f"NACK: File giải mã không hợp lệ - {metadata['filename']}",
                    is_nack=True
                )
                db.session.add(nack_msg)
                db.session.commit()
                
                steps.append("❌ Dữ liệu giải mã không phải ảnh hợp lệ!")
                steps.append(f"❗ Magic number (hex): {img_data[:8].hex()}")
                return render_template("decrypt_packet.html", msg=msg, steps=steps)

            # 9. Lưu ảnh đã giải mã
            out_filename = f"decrypted_{int(time.time())}_{secure_filename(metadata['filename'])}"
            out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_filename)
            
            with open(out_path, 'wb') as f:
                f.write(img_data)
            
            decrypted_file = out_filename
            steps.append(f"✅ Đã giải mã thành công: {metadata['filename']}")

            # 10. Gửi ACK
            ack_msg = Message(
                sender_id=current_user.id,
                receiver_id=msg.sender_id,
                text=f"ACK: Đã giải mã {metadata['filename']}",
                is_ack=True
            )
            db.session.add(ack_msg)
            db.session.commit()

            return render_template(
                "decrypt_packet.html", 
                msg=msg, 
                steps=steps,
                current_time=int(time.time()),
                expiration_time=metadata.get('expiration'),
                calculated_hash=valid_hash,
                packet_hash=packet['hash'],
                signer_username=metadata.get('sender'),
                signature_time=metadata.get('timestamp'),
                original_filename=metadata.get('filename'),
                file_size=metadata.get('file_size'),
                file_format="JPEG" if img_data.startswith(b'\xFF\xD8') else "PNG" if img_data.startswith(b'\x89PNG') else "Không xác định",
                decrypted_file=decrypted_file
            )

        except Exception as e:
            db.session.rollback()
            steps.append(f"❌ Lỗi hệ thống: {str(e)}")
            app.logger.error(f"Error in decrypt_packet: {str(e)}")
            return render_template("decrypt_packet.html", msg=msg, steps=steps)

    return render_template("decrypt_packet.html", msg=msg, steps=steps, decrypted_file=decrypted_file)

@app.route('/download_decrypted/<filename>')
@login_required
def download_decrypted_file(filename):
    out_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    return send_file(out_path, as_attachment=True, download_name=filename)

@app.route('/download_watermark/<filename>')
@login_required
def download_watermark(filename):
    try:
        return send_file(
            os.path.join(app.config['UPLOAD_FOLDER'], filename),
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        flash(f"Lỗi khi tải watermark: {str(e)}")
        return redirect(url_for('dashboard'))

@app.route('/download_file/<filename>')
@login_required
def download_file(filename):
    try:
        # Xây dựng đường dẫn file đầy đủ
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Kiểm tra file có tồn tại không
        if not os.path.exists(file_path):
            flash("File không tồn tại trên server", "error")
            return redirect(url_for('dashboard'))

        # Lấy thông tin message từ database (nếu có)
        message = Message.query.filter_by(file_name=filename).first()

        # Xác định tên file khi tải về
        if message and message.file_display_name:
            download_name = secure_filename(message.file_display_name)
            # Giữ nguyên phần mở rộng nếu là packet
            if message.is_packet and not download_name.lower().endswith('.json'):
                download_name += '.json'
        else:
            # Xử lý tên file cho các trường hợp đặc biệt
            if filename.startswith("packet_"):
                base_name = secure_filename(filename[7:])
                download_name = f"packet_{base_name if not base_name.endswith('.json') else base_name[:-5]}.json"
            elif filename.startswith("wm_"):
                download_name = f"watermarked_{secure_filename(filename[3:])}"
            elif filename.startswith("decrypted_"):
                download_name = secure_filename(filename[10:])  # Bỏ prefix 'decrypted_'
            else:
                download_name = secure_filename(filename)

        # Xác định mimetype
        if filename.lower().endswith('.json') or (message and message.is_packet):
            mimetype = 'application/json'
        else:
            # Kiểm tra magic number cho các file không phải JSON
            with open(file_path, 'rb') as f:
                header = f.read(32)
                
                if header.startswith(b'\xFF\xD8'):
                    mimetype = 'image/jpeg'
                elif header.startswith(b'\x89PNG'):
                    mimetype = 'image/png'
                else:
                    mimetype = 'application/octet-stream'

        # Thiết lập response
        response = send_file(
            file_path,
            as_attachment=True,
            download_name=download_name,
            mimetype=mimetype
        )
        
        # Thiết lập headers bảo mật và cache
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        
        return response

    except FileNotFoundError:
        flash("Không tìm thấy file trên server", "error")
    except Exception as e:
        flash(f"Lỗi khi tải file: {str(e)}", "error")
        app.logger.error(f"Download error: {str(e)}", exc_info=True)
    
    return redirect(url_for('dashboard'))

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    # Kiểm tra file tồn tại
    if not os.path.exists(file_path):
        abort(404)
    
    # Xác định mimetype
    if filename.lower().endswith('.png'):
        mimetype = 'image/png'
    elif filename.lower().endswith(('.jpg', '.jpeg')):
        mimetype = 'image/jpeg'
    else:
        mimetype = 'application/octet-stream'
    
    return send_file(file_path, mimetype=mimetype)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
