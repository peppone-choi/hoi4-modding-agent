"""
Quality gates for Haiku worker output validation.
G1-G4 (Haiku), G5-G6 (Sonnet/Opus).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum


class GateLevel(Enum):
    G1_SCHEMA = 1
    G2_FORMAT = 2
    G3_SEMANTIC = 3
    G4_CONSISTENCY = 4
    G5_INTEGRATION = 5
    G6_ACCEPTANCE = 6


@dataclass
class ValidationResult:
    gate_level: GateLevel
    passed: bool
    errors: list[str]
    warnings: list[str]
    score: float


class QualityGateValidator:
    """Validates Haiku worker outputs against quality gates."""
    
    def validate(self, output: str, gate_level: GateLevel, schema: dict | None = None) -> ValidationResult:
        """Run validation for specified gate level."""
        validators = {
            GateLevel.G1_SCHEMA: self._validate_g1_schema,
            GateLevel.G2_FORMAT: self._validate_g2_format,
            GateLevel.G3_SEMANTIC: self._validate_g3_semantic,
            GateLevel.G4_CONSISTENCY: self._validate_g4_consistency,
        }
        
        validator = validators.get(gate_level)
        if not validator:
            return ValidationResult(
                gate_level=gate_level,
                passed=False,
                errors=[f"No validator for gate level: {gate_level}"],
                warnings=[],
                score=0.0,
            )
        
        return validator(output, schema)
    
    def _validate_g1_schema(self, output: str, schema: dict | None) -> ValidationResult:
        """G1: Schema conformance (field presence, types)."""
        errors = []
        warnings = []
        
        if not output or not output.strip():
            errors.append("Empty output")
            return ValidationResult(GateLevel.G1_SCHEMA, False, errors, warnings, 0.0)
        
        if schema:
            try:
                if schema.get("type") == "json":
                    parsed = json.loads(output)
                    required_fields = schema.get("required", [])
                    for field in required_fields:
                        if field not in parsed:
                            errors.append(f"Missing required field: {field}")
                
                elif schema.get("type") == "template":
                    template = schema.get("template", "")
                    placeholders = re.findall(r"\{\{(\w+)\}\}", template)
                    for placeholder in placeholders:
                        if f"{{{{{placeholder}}}}}" in output:
                            errors.append(f"Unfilled placeholder: {{{{{placeholder}}}}}")
                
            except json.JSONDecodeError as e:
                errors.append(f"Invalid JSON: {e}")
        
        score = 1.0 if not errors else max(0.0, 1.0 - len(errors) * 0.2)
        return ValidationResult(GateLevel.G1_SCHEMA, len(errors) == 0, errors, warnings, score)
    
    def _validate_g2_format(self, output: str, schema: dict | None) -> ValidationResult:
        """G2: Format validation (syntax, structure)."""
        errors = []
        warnings = []
        
        if schema:
            format_type = schema.get("format")
            
            if format_type == "pdx_script":
                if not self._is_valid_pdx_syntax(output):
                    errors.append("Invalid PDX Script syntax")
            
            elif format_type == "yaml":
                if not self._is_valid_yaml_structure(output):
                    errors.append("Invalid YAML structure")
            
            elif format_type == "json":
                try:
                    json.loads(output)
                except json.JSONDecodeError as e:
                    errors.append(f"Invalid JSON: {e}")
        
        max_length = schema.get("max_length", 10000) if schema else 10000
        if len(output) > max_length:
            warnings.append(f"Output exceeds max length ({len(output)} > {max_length})")
        
        score = 1.0 if not errors else max(0.0, 1.0 - len(errors) * 0.25)
        return ValidationResult(GateLevel.G2_FORMAT, len(errors) == 0, errors, warnings, score)
    
    def _validate_g3_semantic(self, output: str, schema: dict | None) -> ValidationResult:
        """G3: Semantic validation (logic, references)."""
        errors = []
        warnings = []
        
        if schema and "references" in schema:
            referenced_entities = schema["references"]
            for entity in referenced_entities:
                if entity not in output:
                    errors.append(f"Missing expected reference: {entity}")
        
        if schema and "forbidden_patterns" in schema:
            for pattern in schema["forbidden_patterns"]:
                if re.search(pattern, output):
                    errors.append(f"Forbidden pattern found: {pattern}")
        
        if "TODO" in output or "FIXME" in output:
            warnings.append("Contains TODO/FIXME markers")
        
        score = 1.0 if not errors else max(0.0, 1.0 - len(errors) * 0.3)
        return ValidationResult(GateLevel.G3_SEMANTIC, len(errors) == 0, errors, warnings, score)
    
    def _validate_g4_consistency(self, output: str, schema: dict | None) -> ValidationResult:
        """G4: Consistency checks (cross-item, patterns)."""
        errors = []
        warnings = []
        
        if schema and "batch_items" in schema:
            items = schema["batch_items"]
            outputs = output.split("\n---\n") if "\n---\n" in output else [output]
            
            if len(outputs) != len(items):
                errors.append(f"Item count mismatch (expected {len(items)}, got {len(outputs)})")
            
            patterns = set()
            for item_output in outputs:
                pattern_match = re.search(r"^(\w+_\w+)", item_output)
                if pattern_match:
                    patterns.add(pattern_match.group(1).split("_")[0])
            
            if len(patterns) > 1:
                warnings.append(f"Inconsistent naming patterns: {patterns}")
        
        score = 1.0 if not errors else max(0.0, 1.0 - len(errors) * 0.35)
        return ValidationResult(GateLevel.G4_CONSISTENCY, len(errors) == 0, errors, warnings, score)
    
    def _is_valid_pdx_syntax(self, content: str) -> bool:
        """Basic PDX Script syntax validation."""
        brace_count = content.count("{") - content.count("}")
        if brace_count != 0:
            return False
        
        if re.search(r"[{}]\s*[{}]", content):
            return False
        
        return True
    
    def _is_valid_yaml_structure(self, content: str) -> bool:
        """Basic YAML structure validation."""
        lines = content.split("\n")
        
        for line in lines:
            if line.strip() and not line.startswith("#"):
                if ":" not in line and not line.startswith("-"):
                    return False
        
        return True


def validate_output(output: str, gate_level: int, schema: dict | None = None) -> ValidationResult:
    """Convenience function for validating output."""
    validator = QualityGateValidator()
    gate = GateLevel(gate_level)
    return validator.validate(output, gate, schema)


def passes_quality_gate(output: str, gate_level: int, schema: dict | None = None) -> bool:
    """Check if output passes quality gate."""
    result = validate_output(output, gate_level, schema)
    return result.passed and result.score >= 0.7
