"""
QC Validator - Checks measurements against reference standards
Updated to handle Unit conversion (Inch/CM) and JSON size charts with asymmetric tolerances.
"""
import json

class QCValidator:
    def __init__(self, tolerance_cm=1.0):
        # Renamed argument to 'tolerance_cm' to match your main.py call
        self.default_tolerance = tolerance_cm
        
    def parse_value(self, value_str, source_unit="cm"):
        """
        Parses a number string (decimals or fractions) to a float.
        (Removed hardcoded CM to Inch conversion so units stay pure).
        """
        try:
            value_str = str(value_str).strip()
            if not value_str: return 0.0

            val = 0.0
            # 1. Parse the number (Handle fractions like "24 1/2" or "1/4")
            if ' ' in value_str:
                parts = value_str.split(' ')
                whole = float(parts[0])
                if '/' in parts[1]:
                    num, den = parts[1].split('/')
                    frac = float(num) / float(den)
                else:
                    frac = float(parts[1])
                val = whole + frac
            elif '/' in value_str:
                num, den = value_str.split('/')
                val = float(num) / float(den)
            else:
                val = float(value_str)

            # --- NEW CODE: STOP CONVERTING TO INCHES ---
            # Return the pure float regardless of the unit. 
            # This ensures CM is compared to CM, and INCH to INCH.
            return val 
            
        except Exception:
            return 0.0

    def validate_against_reference(self, measurements, reference_data):
        """
        Compare measurements against a reference set (with optional asymmetric tolerances).
        Safely handles both strict decimals and mixed fractions.
        """
        results = []
        failures = []
        total_deviation = 0
        count = 0
        
        # Convert measurements to simple dict for lookup
        measured_map = {}
        for m in measurements:
            try:
                # SAFE FALLBACK: Parses "5 3/8" to 5.375, AND safely parses "5.37" to 5.37
                val = self.parse_value(str(m['value']), source_unit="inch")
                measured_map[m['name']] = val
            except (ValueError, TypeError):
                continue
        
        # Compare each reference item
        for ref_item in reference_data:
            name = ref_item.get('name')
            ref_val = float(ref_item.get('value', 0))
            
            raw_t_plus = float(ref_item.get('tol_plus', self.default_tolerance))
            raw_t_minus = float(ref_item.get('tol_minus', self.default_tolerance))
            
            t_plus = abs(raw_t_plus)
            t_minus = abs(raw_t_minus)
            
            if name in measured_map:
                measured_val = measured_map[name]
                deviation = measured_val - ref_val # Signed deviation
                abs_deviation = abs(deviation)
                
                lower_limit = ref_val - t_minus
                upper_limit = ref_val + t_plus
                
                is_pass = lower_limit <= measured_val <= upper_limit
                status = "PASS" if is_pass else "FAIL"
                
                result = {
                    "name": name,
                    "measured": round(measured_val, 2),
                    "reference": round(ref_val, 2),
                    "deviation": round(deviation, 2),
                    "tol_minus": round(t_minus, 2),
                    "tol_plus": round(t_plus, 2),
                    "status": status
                }
                
                results.append(result)
                
                if status == "FAIL":
                    failures.append(result)
                
                total_deviation += abs_deviation
                count += 1
        
        overall_status = "PASS" if len(failures) == 0 else "FAIL"
        avg_deviation = total_deviation / count if count > 0 else 0
        
        summary = {
            "overall_status": overall_status,
            "total_checks": count,
            "passed": count - len(failures),
            "failed": len(failures),
            "average_deviation": round(avg_deviation, 2)
        }
        
        return overall_status, results, summary
    
    def validate_against_size_standard(self, measurements, detected_size, size_standards, garment_type):
        """
        Validates the extracted measurements against the size standards.
        Matches using the Universal Letter Code (A, B, C...) instead of names.
        Safely handles both strict decimals and mixed fractions.
        """
        qc_results = []
        overall_status = "PASS"
        
        if detected_size == "Unknown" or detected_size == "FAIL":
            return "FAIL", qc_results, []
            
        file_unit = size_standards.get("units", "cm")
        
        raw_std_entry = size_standards.get(garment_type, {})
        size_map = raw_std_entry.get('sizes', raw_std_entry) if isinstance(raw_std_entry, dict) else {}
        standard_list = size_map.get(detected_size, [])
        
        if not standard_list:
            return "PASS", qc_results, []
            
        std_lookup = {}
        for item in standard_list:
            code = item.get('description', '').strip()
            if code:
                std_lookup[code] = item

        for m in measurements:
            m_code = m.get('code', m['name'])
            m_name = m['name'] 
            
            # SAFE FALLBACK: Converts strings like "5 3/8" OR "5.37" back into floats for math
            m_val = self.parse_value(str(m['value']), source_unit="inch") 
            
            status = "INFO" 
            
            if m_code in std_lookup:
                std_item = std_lookup[m_code]
                target_val = self.parse_value(std_item.get('value', 0), file_unit)
                
                raw_t_plus = std_item.get('tol_plus', getattr(self, 'default_tolerance', 1.0))
                raw_t_minus = std_item.get('tol_minus', raw_t_plus)
                
                t_plus = abs(self.parse_value(raw_t_plus, file_unit))
                t_minus = abs(self.parse_value(raw_t_minus, file_unit))
                
                lower_limit = target_val - t_minus
                upper_limit = target_val + t_plus
                
                if lower_limit <= m_val <= upper_limit:
                    status = "PASS"
                else:
                    status = "FAIL"
                    overall_status = "FAIL"
                    
            qc_results.append({
                "name": m_name,     
                "code": m_code,     
                "value": m_val,
                "status": status
            })
            
        return overall_status, qc_results, []
    
    def generate_qc_report_text(self, summary, results):
        """
        Generate human-readable QC report
        """
        report_lines = []
        report_lines.append("=" * 60)
        report_lines.append("QC INSPECTION REPORT")
        report_lines.append("=" * 60)
        
        if "message" in summary:
             report_lines.append(f"Status: {summary['message']}")
             return "\n".join(report_lines)

        report_lines.append(f"Overall Status: {summary['overall_status']}")
        report_lines.append(f"Checks Performed: {summary['total_checks']}")
        report_lines.append(f"Passed: {summary['passed']}")
        report_lines.append(f"Failed: {summary['failed']}")
        
        # Changed 'cm' to 'in'
        report_lines.append(f"Avg Deviation: {summary['average_deviation']} in")
        report_lines.append("=" * 60)
        
        if results:
            report_lines.append(f"{'MEASUREMENT':<35} | {'ACTUAL':<8} | {'TARGET':<8} | {'STATUS':<5}")
            report_lines.append("-" * 65)
            
            for res in results:
                status_icon = "✅" if res['status'] == "PASS" else "❌"
                line = f"{status_icon} {res['name']:<32} | {res['measured']:<8} | {res['reference']:<8} | {res['status']}"
                report_lines.append(line)
                
                if res['status'] == "FAIL":
                    # Show detailed tolerance info for failures
                    # FIX: Changed + to - for the lower limit bound
                    report_lines.append(f"    ↳ Range: [{res['reference'] - res['tol_minus']:.2f} to {res['reference'] + res['tol_plus']:.2f}] (Dev: {res['deviation']})")
        
        return "\n".join(report_lines)