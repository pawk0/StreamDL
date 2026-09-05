import os
import struct
import zlib
import math

def create_png(width, height, pixels):
    """Creates a raw RGBA PNG from a list of (R, G, B, A) pixels."""
    raw_data = bytearray()
    for y in range(height):
        raw_data.append(0)  # filter type 0 (None)
        for x in range(width):
            r, g, b, a = pixels[y * width + x]
            raw_data.extend([r, g, b, a])
    
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

    png = bytearray(b'\x89PNG\r\n\x1a\n')
    # IHDR
    png.extend(chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)))
    # IDAT
    compressed = zlib.compress(bytes(raw_data), level=9)
    png.extend(chunk(b'IDAT', compressed))
    # IEND
    png.extend(chunk(b'IEND', b''))
    return bytes(png)

def generate_icon(size):
    pixels = []
    center_x = size / 2.0
    center_y = size / 2.0
    radius = size * 0.46

    for y in range(size):
        for x in range(size):
            dx = x - center_x
            dy = y - center_y
            dist = math.sqrt(dx * dx + dy * dy)
            
            # Corner rounded rectangle / circle mask
            if dist <= radius:
                # Gradient background (Violet to Cyan)
                factor = (x + y) / (2.0 * size)
                r = int(99 + (6 - 99) * factor)
                g = int(102 + (182 - 102) * factor)
                b = int(241 + (212 - 241) * factor)
                a = 255

                # Draw Play triangle inside
                # Normalized coords in [-1, 1] relative to inner circle
                nx = (x - center_x) / (size * 0.35)
                ny = (y - center_y) / (size * 0.35)

                # Triangle pointing right: nx >= -0.5, ny >= -0.7*(nx + 0.8), ny <= 0.7*(nx + 0.8), nx <= 0.7
                if -0.35 <= nx <= 0.6 and abs(ny) <= 0.9 * (0.6 - nx):
                    r, g, b, a = 255, 255, 255, 255
                
                pixels.append((r, g, b, a))
            else:
                # Transparent outside
                pixels.append((0, 0, 0, 0))

    return create_png(size, size, pixels)

os.makedirs("extension/icons", exist_ok=True)
for s in [16, 48, 128]:
    png_data = generate_icon(s)
    path = f"extension/icons/icon{s}.png"
    with open(path, "wb") as f:
        f.write(png_data)
    print(f"Generated {path} ({s}x{s})")
