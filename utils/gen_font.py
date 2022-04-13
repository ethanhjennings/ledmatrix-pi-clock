import sys
import math

def pixels_to_hex(pixels, width):
    pixels = pixels.strip()
    pixel_bin = 0
    for p in pixels:
        pixel_bin <<= 1
        if p == '#':
           pixel_bin += 1

    byte_width = int(math.ceil(width / 8))
    pixel_bin <<= (byte_width*8-len(pixels))
    return hex(pixel_bin)[2:]

def parse_char(char, char_data):
    bdf_data = ""
    width = max(len(l.strip()) for l in char_data)
    height = len(char_data)
    codepoint = ord(char)
    dwidth = width + 1
    bdf_data += "\n"
    bdf_data += f"STARTCHAR {char}\n"
    bdf_data += f"ENCODING {codepoint}\n"
    bdf_data += f"SWIDTH 500 0\n"
    bdf_data += f"DWIDTH {dwidth} 0\n"
    bdf_data += f"BBX {width} {height} 0 0\n"
    bdf_data += "BITMAP\n"

    for line in char_data:
       bdf_data += pixels_to_hex(line, width) + '\n'

    bdf_data += "ENDCHAR\n"
    
    return bdf_data, width, height

def gen_header(name, width, height, num_chars):
    bdf_file =  f"STARTFONT 2.1\n"
    bdf_file += f"FONT {name}\n"
    bdf_file += f"SIZE {width} {height} 75 75\n"
    bdf_file += f"FONTBOUNDINGBOX {width} {height} 0 0\n"
    bdf_file += f"STARTPROPERTIES 2\n"
    bdf_file += f"FONT_ASCENT {height}\n"
    bdf_file += f"FONT_DESCENT 0\n"
    bdf_file += f"ENDPROPERTIES\n"
    bdf_file += f"CHARS {num_chars}\n"
    return bdf_file

def parse_font(name, font_data):
    char = None
    char_data = []
    max_width = 0
    max_height = 0
    bdf_file = ""
    char_count = 1
    
    for line in font_data:
        if len(line.strip()) == 0:
            # Ignore empty lines
            continue
        elif line.startswith('='):
            # Start new character
            if char is not None:
                new_char, width, height = parse_char(char, char_data)
                bdf_file += new_char
                max_width = max(width, max_width)
                max_height = max(height, max_height)
                char_count += 1
            char = line[1]
            char_data = []
        else:
            char_data.append(line)
    new_char, width, height = parse_char(char, char_data)
    bdf_file += new_char
    max_width = max(width, max_width)
    max_height = max(height, max_height)

    bdf_file = gen_header(name, max_width, max_height, char_count) + bdf_file
    bdf_file += "\nENDFONT"

    return bdf_file

if __name__ == "__main__":
    pathname = sys.argv[1]
    font_name = pathname.split('.')[0]
    with open(pathname) as f:
        print(''.join(parse_font(font_name, f.readlines())))
