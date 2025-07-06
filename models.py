from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    public_key = db.Column(db.LargeBinary)
    private_key = db.Column(db.LargeBinary)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    text = db.Column(db.Text)
    file_name = db.Column(db.String(100))    # Tên file vật lý đã lưu (không dấu, prefix thời gian)
    file_display_name = db.Column(db.String(200))  # Tên gốc hiển thị cho user (có dấu, khoảng trắng)
    is_key = db.Column(db.Boolean, default=False)
    is_packet = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    is_ack = db.Column(db.Boolean, default=False)
    is_nack = db.Column(db.Boolean, default=False)

class Handshake(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(20), default='pending')  # pending/accepted/rejected
    created_at = db.Column(db.DateTime, default=db.func.now())
    session_key = db.Column(db.LargeBinary)  # Có thể dùng hoặc không, tùy yêu cầu của app
