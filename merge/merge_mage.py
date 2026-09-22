import cv2
import json
import numpy as np

# Your provided data
data = [
    {"px": 214.02, "name": "Neck Width", "unit": "in", "value": "5.16", "coords": {"p1": [241, 364], "p2": [455, 361]}, "status": "PASS"}, 
    {"px": 133.40, "name": "Sleeve Length from Shoulder Seam", "unit": "in", "value": "3.22", "coords": {"p1": [500, 373], "p2": [607, 453]}, "status": "PASS"}, 
    {"px": 341.05, "name": "CPSC - Chest Armpit to Armpit", "unit": "in", "value": "8.23", "coords": {"p1": [176, 556], "p2": [517, 550]}, "status": "FAIL"}, 
    {"px": 487.01, "name": "CF Body Length (Low Neck)", "unit": "in", "value": "11.75", "coords": {"p1": [241, 364], "p2": [245, 851]}, "status": "INFO"}, 
    {"px": 103.24, "name": "Sleeve Opening - Short", "unit": "in", "value": "2.49", "coords": {"p1": [607, 453], "p2": [569, 549]}, "status": "FAIL"}, 
    {"px": 108.70, "name": "Sleeve Opening - Short", "unit": "in", "value": "2.62", "coords": {"p1": [80, 462], "p2": [131, 558]}, "status": "FAIL"}, 
    {"px": 127.01, "name": "CPSC - Upper Arm", "unit": "in", "value": "3.06", "coords": {"p1": [577, 430], "p2": [530, 548]}, "status": "FAIL"}, 
    {"px": 173.28, "name": "Armpit to Sleeve Top Edge (Right)", "unit": "in", "value": "4.18", "coords": {"p1": [517, 550], "p2": [507, 377]}, "status": "INFO"}, 
    {"px": 361.01, "name": "CPSC - Bottom Sweep Straight (CPSC Waist)", "unit": "in", "value": "8.71", "coords": {"p1": [164, 841], "p2": [525, 838]}, "status": "FAIL"}, 
    {"px": 288.11, "name": "Side Seam Right (Armpit to Hem)", "unit": "in", "value": "6.95", "coords": {"p1": [517, 550], "p2": [525, 838]}, "status": "INFO"}
]

def generate_short_name(full_name):
    """Creates an acronym from the full name (e.g., 'Neck Width' -> 'NW')"""
    # Remove hyphens and parentheses to clean up the text
    clean_text = full_name.replace('-', ' ').replace('(', '').replace(')', '')
    # Take the first letter of each word and capitalize it
    return "".join([word[0].upper() for word in clean_text.split() if word])

# 1. Load your image here
# Replace 'garment.jpg' with the path to your actual image file
image_path = 'merge\garment.webp'
image = cv2.imread(image_path)

# Fallback: Create a blank white canvas if the image file isn't found
if image is None:
    print(f"Could not load image at {image_path}. Using a blank canvas for demonstration.")
    image = np.ones((1000, 800, 3), dtype=np.uint8) * 255

# 2. Loop through the data and plot the points
for item in data:
    short_name = generate_short_name(item['name'])
    
    # Extract coordinates
    p1 = tuple(item['coords']['p1'])
    p2 = tuple(item['coords']['p2'])
    
    # Draw Point 1 (Red circle) and its label
    cv2.circle(image, p1, radius=5, color=(0, 0, 255), thickness=-1)
    cv2.putText(image, f"{short_name}-1", (p1[0] + 8, p1[1] - 8), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    
    # Draw Point 2 (Blue circle) and its label
    cv2.circle(image, p2, radius=5, color=(255, 0, 0), thickness=-1)
    cv2.putText(image, f"{short_name}-2", (p2[0] + 8, p2[1] - 8), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)

# 3. Save or display the result
output_filename = 'annotated_points.jpg'
cv2.imwrite(output_filename, image)
print(f"Image successfully saved as {output_filename}")

# Uncomment the lines below if you want a popup window to view the image immediately
# cv2.imshow('Measurement Points', image)
# cv2.waitKey(0)
# cv2.destroyAllWindows()