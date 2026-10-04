"""Controlled, evidence-backed position facets; independent of question categories."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

TAXONOMY_VERSION = 1


class PositionCategory(StrEnum):
    BACKEND = "后端"
    FRONTEND = "前端"
    CLIENT = "客户端"
    AI = "算法/AI"
    TEST = "测试"
    OPS = "运维/SRE"
    DATA = "数据"
    SECURITY = "安全"
    GAME = "游戏"
    SYSTEM = "嵌入式/系统"
    OTHER = "其他"


SPECIALIZATIONS = (
    "通用后端",
    "基础架构",
    "分布式系统",
    "存储",
    "数据库",
    "中间件",
    "音视频",
    "网络",
    "云原生",
    "AI Infra",
    "CV",
    "NLP",
    "推荐算法",
    "搜索算法",
    "广告算法",
    "大模型",
    "多模态",
    "语音",
    "机器学习平台",
    "AI应用",
    "Agent",
    "RAG",
    "模型评测",
    "Android",
    "iOS",
    "Windows",
    "macOS",
    "跨端",
    "客户端基础架构",
    "Web",
    "小程序",
    "全栈",
    "自动化测试",
    "性能测试",
    "质量保障",
    "可靠性工程",
    "数据仓库",
    "实时计算",
    "数据分析",
    "攻防",
    "应用安全",
    "风控",
    "游戏客户端",
    "游戏引擎",
    "嵌入式",
    "系统软件",
)
DOMAINS = (
    "电商",
    "广告",
    "搜索",
    "推荐",
    "直播",
    "短视频",
    "社交",
    "游戏",
    "支付",
    "金融",
    "云计算",
    "企业服务",
    "自动驾驶",
    "智能硬件",
)
SKILLS = (
    "C++",
    "C",
    "Java",
    "Go",
    "Python",
    "Rust",
    "JavaScript",
    "TypeScript",
    "SQL",
    "React",
    "Vue",
    "Next.js",
    "Node.js",
    "Spring",
    "Spring Boot",
    "MySQL",
    "PostgreSQL",
    "Redis",
    "Kafka",
    "Linux",
    "TCP/IP",
    "HTTP",
    "CUDA",
    "PyTorch",
    "TensorFlow",
    "Docker",
    "Kubernetes",
    "FFmpeg",
    "Spark",
    "Flink",
    "Hive",
    "Unity",
    "Unreal",
)
SKILL_ALIASES = {
    "Golang": "Go",
    "golang": "Go",
    "CPP": "C++",
    "cpp": "C++",
    "SpringBoot": "Spring Boot",
    "springboot": "Spring Boot",
    "Postgres": "PostgreSQL",
    "K8s": "Kubernetes",
    "k8s": "Kubernetes",
    "JS": "JavaScript",
    "TS": "TypeScript",
}


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(
        pattern=r"^(category|raw_title|normalized_title|specializations|domains|skills)$"
    )
    value: str
    quote: str = Field(min_length=2)
    source: str = Field(pattern=r"^(declared|responsibility|interview|project|inferred)$")


class PositionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_title: str | None = None
    normalized_title: str | None = None
    category: PositionCategory | None = None
    specializations: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    status: str = Field(default="uncertain", pattern=r"^(classified|uncertain|out_of_scope)$")
    source: str = Field(default="inferred", pattern=r"^(declared|inferred)$")
    needs_review: bool = True
    human_reviewed: bool = False
    source_changed: bool = False
    evidence: list[Evidence] = Field(default_factory=list)
    taxonomy_version: int = TAXONOMY_VERSION

    @model_validator(mode="after")
    def controlled_values(self):
        for field, vocabulary in (
            ("specializations", SPECIALIZATIONS),
            ("domains", DOMAINS),
            ("skills", SKILLS),
        ):
            values = getattr(self, field)
            if field == "skills":
                values = [SKILL_ALIASES.get(v, v) for v in values]
            if set(values) - set(vocabulary):
                raise ValueError(f"unsupported {field}: {set(values) - set(vocabulary)}")
            setattr(self, field, list(dict.fromkeys(values)))
        if self.taxonomy_version != TAXONOMY_VERSION:
            raise ValueError("unsupported taxonomy version")
        if (self.status == "classified") != (self.category is not None):
            raise ValueError("only classified profiles may have a category")
        # Model confidence is never sufficient to bypass review of inference.
        if self.source_changed:
            self.needs_review = True
        elif self.human_reviewed:
            self.needs_review = False
        elif self.source == "inferred" or self.status != "classified":
            self.needs_review = True
        return self


def validate_evidence(profile: PositionProfile, author_text: str) -> PositionProfile:
    """Drop unsupported labels; never treat a fabricated quote as evidence."""
    data = profile.model_dump(mode="json")
    # Extraction and caches cannot claim a human approved an LLM output.
    data["human_reviewed"] = False
    data["source_changed"] = False
    evidence = [e for e in profile.evidence if e.quote in author_text]
    # A skill quote must actually mention that skill, not an arbitrary sentence.
    evidence = [
        e
        for e in evidence
        if e.field != "skills"
        or any(
            re.search(
                r"(?<![A-Za-z0-9])"
                + re.escape(token)
                + (r"(?![A-Za-z0-9+])" if token == "C" else r"(?![A-Za-z0-9])"),
                e.quote,
                re.I,
            )
            for token in [
                e.value,
                *[alias for alias, canonical in SKILL_ALIASES.items() if canonical == e.value],
            ]
        )
    ]
    data["evidence"] = [e.model_dump() for e in evidence]
    for field in ("specializations", "domains", "skills"):
        data[field] = [
            value
            for value in data[field]
            if any(
                e.field == field and SKILL_ALIASES.get(e.value, e.value) == value for e in evidence
            )
        ]
    if profile.raw_title and profile.raw_title not in author_text:
        data["raw_title"] = None
        data["source"] = "inferred"
    if data["raw_title"] and re.fullmatch(
        r"(?:CSIG|PCG|TEG|CDG|OD|ICT\s*BG|日常实习生|暑期实习生|校企合作|笔试|文心一言|技术岗|AI岗位|AI相关岗|未知)",
        data["raw_title"],
        re.I,
    ):
        data["category"] = None
        data["status"] = "uncertain"
    if profile.category and not any(
        e.field == "category" and e.value == profile.category for e in evidence
    ):
        data["category"] = None
        data["status"] = "uncertain"
    if data["source"] == "declared" and not data["raw_title"]:
        data["source"] = "inferred"
    if profile.category:
        category_evidence = [e for e in evidence if e.field == "category"]
        if not category_evidence or any(e.source != "declared" for e in category_evidence):
            data["needs_review"] = True
        if data["raw_title"]:
            conservative = preview_title(data["raw_title"])
            if conservative.category != profile.category:
                data["needs_review"] = True
    if any(e.source == "inferred" for e in evidence):
        data["needs_review"] = True
    return PositionProfile.model_validate(data)


def profile_tool_schema() -> dict:
    """Inline Pydantic definitions so nested tool schemas have no dangling $refs."""
    schema = PositionProfile.model_json_schema()
    definitions = schema.pop("$defs", {})
    schema["properties"].pop("human_reviewed", None)
    schema["properties"].pop("source_changed", None)

    def inline(value):
        if isinstance(value, list):
            return [inline(v) for v in value]
        if isinstance(value, dict):
            if "$ref" in value:
                return inline(definitions[value["$ref"].rsplit("/", 1)[-1]])
            return {k: inline(v) for k, v in value.items()}
        return value

    result = inline(schema)
    for field, vocabulary in (
        ("specializations", SPECIALIZATIONS),
        ("domains", DOMAINS),
        ("skills", SKILLS),
    ):
        result["properties"][field]["items"]["enum"] = list(vocabulary)
    result["properties"]["status"]["enum"] = ["classified", "uncertain", "out_of_scope"]
    result["properties"]["source"]["enum"] = ["declared", "inferred"]
    evidence_properties = result["properties"]["evidence"]["items"]["properties"]
    evidence_properties["field"]["enum"] = [
        "category",
        "raw_title",
        "normalized_title",
        "specializations",
        "domains",
        "skills",
    ]
    evidence_properties["source"]["enum"] = [
        "declared",
        "responsibility",
        "interview",
        "project",
        "inferred",
    ]
    return result


def preview_title(title: str) -> PositionProfile:
    """Conservative historical proposal. No guesses from a language or generic questions."""
    rules = (
        (r"测试|测开|质量保障|游测", PositionCategory.TEST),
        (r"安全工程师|安全研发|渗透|攻防", PositionCategory.SECURITY),
        (r"嵌入式|固件|底层开发|系统软件", PositionCategory.SYSTEM),
        (r"运维|\bSRE\b", PositionCategory.OPS),
        (r"数据开发|数据分析|大数据开发|数仓", PositionCategory.DATA),
        (r"Unity|Unreal|游戏客户端|游戏引擎", PositionCategory.GAME),
        (r"前端", PositionCategory.FRONTEND),
        (r"Android|安卓|iOS|客户端", PositionCategory.CLIENT),
        (r"后端|后台开发|服务端|基础架构|AI\s*Infra|推理加速|算子开发", PositionCategory.BACKEND),
        (
            r"算法工程师|算法岗|算法实习|算法研发|(?:大模型|推荐|搜索|广告|NLP|CV|多模态|AIGC|AI|搜推|搜广推).{0,4}算法|AI应用|AI\s*应用|Agent.*开发|智能体.*开发|大模型.*研发",
            PositionCategory.AI,
        ),
    )
    category = next((c for pattern, c in rules if re.search(pattern, title, re.I)), None)
    non_rd = bool(re.search(r"产品经理|运营|法务|采购|商务|美术|游戏策划", title))
    # Multiple explicit jobs (e.g. frontend + backend) require per-mention review.
    if "前端" in title and "后端" in title:
        category = None
    if non_rd:
        category = None
    profile = PositionProfile(
        raw_title=title or None,
        normalized_title=None,
        category=category,
        status="classified" if category else "out_of_scope" if non_rd else "uncertain",
        source="declared" if category else "inferred",
        needs_review=True,
        evidence=[Evidence(field="category", value=category, quote=title, source="declared")]
        if category and len(title) >= 2
        else [],
    )
    patterns = {
        "specializations": {
            "Agent": r"agent|智能体",
            "RAG": r"\bRAG\b",
            "大模型": r"大模型|LLM",
            "AI Infra": r"AI\s*Infra|训推|推理加速|算子开发",
            "Android": r"Android|安卓",
            "iOS": r"iOS",
            "基础架构": r"基础架构",
            "音视频": r"音视频|转码",
            "推荐算法": r"推荐算法|搜推算法|搜广推算法",
            "全栈": r"全栈",
        },
        "domains": {
            "直播": r"直播",
            "电商": r"电商",
            "支付": r"支付",
            "游戏": r"游戏",
            "金融": r"金融",
            "广告": r"广告",
            "短视频": r"短视频",
        },
        "skills": {
            "C++": r"C\+\+",
            "Java": r"(?<![A-Za-z])Java(?![A-Za-z])",
            "Go": r"(?<![A-Za-z])Go(?:lang)?(?![A-Za-z])",
            "Python": r"(?<![A-Za-z])Python(?![A-Za-z])",
            "Rust": r"(?<![A-Za-z])Rust(?![A-Za-z])",
        },
    }
    for field, labels in patterns.items():
        for label, pattern in labels.items():
            match = re.search(pattern, title, re.I)
            if match:
                getattr(profile, field).append(label)
                profile.evidence.append(
                    Evidence(field=field, value=label, quote=title, source="declared")
                )
    return profile
