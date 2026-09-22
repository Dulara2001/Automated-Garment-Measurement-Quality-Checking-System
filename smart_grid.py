import cv2
import numpy as np

class SmartGridSystem:
    def __init__(self, width, height):
        self.w = width
        self.h = height
        
        # Grid Configuration
        self.center_x = int(width / 2)
        # 5% buffer zone around center
        self.buffer = int(width * 0.05)
        
        self.left_limit = self.center_x + self.buffer  # Max X for Left Zone
        self.right_limit = self.center_x - self.buffer # Min X for Right Zone
        
    def validate_point_location(self, x, y, point_id, zone_config):
        """
        Validates if a point is in the correct zone.
        """
        required_zone = None
        if point_id in zone_config.get('left_zone', []):
            required_zone = 'left'
        elif point_id in zone_config.get('right_zone', []):
            required_zone = 'right'
        
        if not required_zone:
            return True, "OK"
            
        # Horizontal Check
        if required_zone == 'left':
            if x > self.left_limit:
                return False, f"Grid Error: Left-side point ({point_id}) found on Right side (x={x})"
        elif required_zone == 'right':
            if x < self.right_limit:
                return False, f"Grid Error: Right-side point ({point_id}) found on Left side (x={x})"
                
        # Vertical Safety Check
        if y > self.h * 0.98 or y < self.h * 0.02:
             return False, f"Grid Error: Point {point_id} on image edge"

        return True, "OK"

    def draw_grid_on_image(self, image):
        """Draws the grid lines for visual debugging"""
        overlay = image.copy()
        h, w = image.shape[:2]
        
        # Draw Zones
        cv2.line(overlay, (self.center_x, 0), (self.center_x, h), (0, 255, 255), 1)
        cv2.line(overlay, (self.left_limit, 0), (self.left_limit, h), (0, 255, 0), 1)
        cv2.line(overlay, (self.right_limit, 0), (self.right_limit, h), (0, 255, 0), 1)
        
        # Labels
        cv2.putText(overlay, "LEFT ZONE", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(overlay, "RIGHT ZONE", (w - 140, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        
        return cv2.addWeighted(overlay, 0.2, image, 0.8, 0)