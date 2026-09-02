"""Structured-output schemas used by the local LLM client."""

from typing import Any

APPS = ["gmail", "outlook", "sheets", "erp", "drive", "slack", "browser", "pdf"]
ACTIONS = ["read", "create", "update", "delete", "send", "extract", "search", "navigate"]

SYNTHESISE_EVENTS: dict[str, Any] = {
    "name": "synthesise_event_sequence",
    "description": "Emit a plausible observable event sequence for a described workflow.",
    "input_schema": {
        "type": "object",
        "properties": {
            "workflow_name": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "app": {"type": "string", "enum": APPS},
                        "action": {"type": "string", "enum": ACTIONS},
                        "object_type": {"type": "string"},
                        "duration_seconds": {"type": "integer"},
                        "note": {"type": "string"},
                    },
                    "required": ["app", "action", "object_type", "duration_seconds"],
                },
            },
            "per_week": {"type": "number", "description": "Times per person per week."},
            "likely_users": {"type": "integer"},
        },
        "required": ["workflow_name", "steps", "per_week", "likely_users"],
    },
}

GENERATE_FLOW: dict[str, Any] = {
    "name": "emit_flow_definition",
    "description": "Emit a runnable automation flow definition for a detected workflow.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "trigger": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "email_received",
                            "schedule",
                            "file_created",
                            "record_updated",
                            "manual",
                        ],
                    },
                    "filter": {"type": "object", "additionalProperties": True},
                },
                "required": ["type"],
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string", "enum": ACTIONS},
                        "connector": {"type": "string", "enum": APPS},
                        "description": {"type": "string"},
                        "inputs": {"type": "object", "additionalProperties": True},
                        "outputs": {"type": "array", "items": {"type": "string"}},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "type", "connector", "outputs", "depends_on"],
                },
            },
            "guards": {
                "type": "object",
                "properties": {
                    "requires_approval_if": {"type": "string"},
                    "irreversible": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "required": ["name", "trigger", "steps", "guards"],
    },
}

SCORE_VARIANCE: dict[str, Any] = {
    "name": "score_workflow_variance",
    "description": "Score how much irreducible human judgement a workflow requires.",
    "input_schema": {
        "type": "object",
        "properties": {
            "judgement_ratio": {"type": "number", "minimum": 0, "maximum": 1},
            "build_effort": {"type": "integer", "minimum": 1, "maximum": 5},
            "reasoning": {"type": "string"},
        },
        "required": ["judgement_ratio", "build_effort", "reasoning"],
    },
}

REMAP_FIELD: dict[str, Any] = {
    "name": "propose_field_remapping",
    "description": "Propose a remapping for a dependency field that no longer resolves.",
    "input_schema": {
        "type": "object",
        "properties": {
            "to_field": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string"},
        },
        "required": ["to_field", "confidence", "rationale"],
    },
}

PROPOSE_RULE: dict[str, Any] = {
    "name": "propose_branch_rule",
    "description": "Propose a branch rule learned from repeated human decisions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "condition": {"type": "string"},
            "action": {"type": "string"},
            "rationale": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["condition", "action", "rationale", "confidence"],
    },
}

READ_FRAMES: dict[str, Any] = {
    "name": "read_recorded_frames",
    "description": "Identify the application and action shown in each recorded frame.",
    "input_schema": {
        "type": "object",
        "properties": {
            "workflow_name": {"type": "string"},
            "frames": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "app": {"type": "string", "enum": APPS},
                        "action": {"type": "string", "enum": ACTIONS},
                        "object_type": {"type": "string"},
                        "skip": {
                            "type": "boolean",
                            "description": "True when the frame shows no meaningful change.",
                        },
                    },
                    "required": ["app", "action", "object_type"],
                },
            },
        },
        "required": ["workflow_name", "frames"],
    },
}

DISCOVER_WORKFLOWS: dict[str, Any] = {
    "name": "discover_repetitive_workflows",
    "description": (
        "Propose which observed activity patterns may represent the same "
        "repetitive human workflow. Cite atlas ids only; do not invent steps "
        "or counts."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "proposed_workflows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "proposal_id": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "supporting_signature_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "supporting_motif_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "supporting_sample_instance_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "core_steps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "token": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                                "required": ["token"],
                            },
                        },
                        "optional_steps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "token": {"type": "string"},
                                    "frequency": {"type": "number"},
                                    "reason": {"type": "string"},
                                },
                                "required": ["token"],
                            },
                        },
                        "observed_applications": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "repetition_assessment": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "strength": {
                                    "type": "string",
                                    "enum": ["low", "medium", "high"],
                                },
                                "reason": {"type": "string"},
                            },
                            "required": ["strength"],
                        },
                        "automation_assessment": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "deterministic_steps": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "judgment_steps": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "potentially_automatable": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "human_approval_points": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                        "confidence": {"type": "number"},
                        "evidence_gaps": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "name",
                        "supporting_signature_ids",
                        "core_steps",
                        "confidence",
                    ],
                },
            },
            "unrelated_patterns": {
                "type": "array",
                "items": {"type": "string"},
            },
            "analysis_notes": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["proposed_workflows", "unrelated_patterns", "analysis_notes"],
    },
}

INVESTIGATE_WORKFLOW: dict[str, Any] = {
    "name": "investigate_workflow_semantics",
    "description": (
        "Classify semantic relationships for a candidate workflow using only "
        "the supplied evidence packet. Cite evidence_ids; do not invent facts."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "conclusions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "relationship": {
                            "type": "string",
                            "enum": [
                                "same_workflow",
                                "optional_step",
                                "conditional_step",
                                "separate_workflow",
                                "insufficient_evidence",
                            ],
                        },
                        "confidence": {"type": "number"},
                        "reasoning": {"type": "string"},
                        "evidence_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "evidence_gaps": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "subject": {"type": "string"},
                    },
                    "required": ["relationship", "confidence", "evidence_ids"],
                },
            },
            "semantic_relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "source_destination",
                                "transformation",
                                "unrelated",
                                "unknown",
                                "insufficient_evidence",
                            ],
                        },
                        "from_token": {"type": "string"},
                        "to_token": {"type": "string"},
                        "confidence": {"type": "number"},
                        "evidence_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "evidence_gaps": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["kind", "evidence_ids"],
                },
            },
            "evidence_gaps": {
                "type": "array",
                "items": {"type": "string"},
            },
            "investigation_notes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "final_decision": {
                "type": "string",
                "enum": ["safe_to_continue", "insufficient_evidence"],
            },
        },
        "required": [
            "conclusions",
            "semantic_relationships",
            "evidence_gaps",
            "investigation_notes",
            "final_decision",
        ],
    },
}
