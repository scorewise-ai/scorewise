from PIL import Image
import os

# Path to your source favicon.png
input_image_path = "favicon.png"

# Output sizes and filenames
output_files = {
    "favicon.ico": [(16, 16), (32, 32), (48, 48)],  # ICO can contain multiple sizes
    "favicon-16x16.png": (16, 16),
    "favicon-32x32.png": (32, 32),
    "apple-touch-icon.png": (180, 180)
}

# Open your favicon.png
img = Image.open(input_image_path)

# Create output directory if it doesn't exist
output_dir = "static"
os.makedirs(output_dir, exist_ok=True)

# Generate favicon.ico with multiple sizes
ico_sizes = output_files["favicon.ico"]
ico_images = [img.resize(size, Image.LANCZOS) for size in ico_sizes]
ico_path = os.path.join(output_dir, "favicon.ico")
ico_images[0].save(ico_path, format='ICO', sizes=ico_sizes)

# Generate PNG files
for filename, size in output_files.items():
    if filename == "favicon.ico":
        continue
    resized_img = img.resize(size, Image.LANCZOS)
    resized_img.save(os.path.join(output_dir, filename), format='PNG')

print("Favicons generated:", list(output_files.keys()))
