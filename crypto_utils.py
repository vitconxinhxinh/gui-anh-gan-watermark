import base64
from Crypto.Hash import SHA512
from hashlib import sha512
from Crypto.Cipher import DES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from PIL import Image, ImageDraw, ImageFont

def pad(data):
    pad_len = 8 - (len(data) % 8)
    return data + bytes([pad_len]) * pad_len

def unpad(data):
    pad_len = data[-1]
    return data[:-pad_len]

def encrypt_des(data, key, iv):
    cipher = DES.new(key, DES.MODE_CBC, iv)
    return cipher.encrypt(pad(data))

def decrypt_des(ciphertext, key, iv):
    cipher = DES.new(key, DES.MODE_CBC, iv)
    return unpad(cipher.decrypt(ciphertext))

def sha512_hash(data):
    return sha512(data).hexdigest()

def sign_data(data, private_key_bytes):
    try:
        key = RSA.import_key(private_key_bytes)
        h = SHA512.new(data)
        sig = pkcs1_15.new(key).sign(h)
        return base64.b64encode(sig)
    except Exception as e:
        raise ValueError(f"Lỗi tạo chữ ký: {str(e)}")

def verify_signature(data, sig_b64, public_key_bytes):
    try:
        key = RSA.import_key(public_key_bytes)
        h = SHA512.new(data)
        sig = base64.b64decode(sig_b64)
        pkcs1_15.new(key).verify(h, sig)
        return True
    except (ValueError, TypeError) as e:
        return False
    except Exception as e:
        raise ValueError(f"Lỗi xác thực chữ ký: {str(e)}")

def encrypt_session_key(session_key, public_key_bytes):
    if not isinstance(session_key, bytes) or len(session_key) != 8:
        raise ValueError("Session key phải là 8 bytes")
    
    if not isinstance(public_key_bytes, bytes):
        raise ValueError("Public key phải ở dạng bytes")
    
    try:
        # Chuyển đổi public key từ bytes sang đối tượng RSA
        key = RSA.import_key(public_key_bytes)
        cipher = PKCS1_v1_5.new(key)
        
        # Mã hóa session key
        encrypted_key = cipher.encrypt(session_key)
        
        # Trả về dạng base64 để dễ lưu trữ/truyền
        return base64.b64encode(encrypted_key)
        
    except Exception as e:
        raise ValueError(f"Lỗi mã hóa session key: {str(e)}")

def decrypt_session_key(enc_key_b64, private_key_bytes):

    if not isinstance(enc_key_b64, (bytes, str)):
        raise ValueError("Encrypted key phải là string hoặc bytes")
    
    if not isinstance(private_key_bytes, bytes):
        raise ValueError("Private key phải ở dạng bytes")
    
    try:
        private_key = RSA.import_key(private_key_bytes)
        cipher = PKCS1_v1_5.new(private_key)

        if isinstance(enc_key_b64, str):
            enc_key_b64 = enc_key_b64.encode('utf-8')
        enc_key = base64.b64decode(enc_key_b64)

        sentinel = b'error'
        session_key = cipher.decrypt(enc_key, sentinel)

        if session_key == sentinel or len(session_key) != 8:
            raise ValueError("Session key giải mã không hợp lệ")

        return session_key

    except Exception as e:
        raise ValueError(f"Lỗi giải mã session key: {str(e)}")

def add_watermark(input_image, watermark_text, output_image):
    from PIL import Image, ImageDraw, ImageFont
    # Mở ảnh gốc và chuyển sang RGB
    image = Image.open(input_image).convert('RGB')
    w, h = image.size
    
    # Tạo một ảnh mới trong suốt với kích thước bằng ảnh gốc
    txt_img = Image.new('RGBA', (w, h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(txt_img)
    
    # Xác định kích thước font
    font_size = int(min(w, h) / 12)  # Giảm kích thước font để phù hợp hơn
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
        except:
            font = ImageFont.load_default()
    
    # Tính toán vị trí để vẽ chữ (giữa ảnh)
    bbox = draw.textbbox((0, 0), watermark_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (w - text_w) / 2
    y = (h - text_h) / 2
    
    # Vẽ watermark với độ trong suốt cao hơn
    draw.text((x, y), watermark_text, font=font, fill=(255, 0, 0, 60))  # Giảm độ đậm
    
    # Xoay watermark 20 độ thay vì 30 độ
    txt_img_rotated = txt_img.rotate(20, expand=True, resample=Image.BICUBIC)
    
    # Tính toán lại kích thước sau khi xoay
    txt_w, txt_h = txt_img_rotated.size
    
    # Tính toán vị trí cắt để đặt watermark vào giữa
    left = (txt_w - w) // 2
    top = (txt_h - h) // 2
    right = left + w
    bottom = top + h
    
    txt_img_cropped = txt_img_rotated.crop((left, top, right, bottom))
    
    # Tạo ảnh gốc dạng RGBA để chồng ảnh
    image_rgba = image.copy().convert('RGBA')
    
    # Chồng ảnh watermark lên ảnh gốc
    watermarked = Image.alpha_composite(image_rgba, txt_img_cropped)
    
    # Chuyển về RGB và lưu
    watermarked.convert('RGB').save(output_image, quality=95)


def make_des_key(raw: bytes) -> bytes:
    if len(raw) < 8:
        return raw.ljust(8, b'0')
    elif len(raw) > 8:
        return raw[:8]
    return raw
