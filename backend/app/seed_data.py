from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5


@dataclass(frozen=True)
class CuratedExample:
    key: str
    mode: str
    seed_text: str | None
    original_title: str
    original_text: str
    final_title: str
    final_text: str
    completed_at: datetime

    @property
    def run_id(self) -> str:
        return str(uuid5(NAMESPACE_URL, f"zao-agugent/{self.key}/run"))

    @property
    def formal_meme_id(self) -> str:
        return str(uuid5(NAMESPACE_URL, f"zao-agugent/{self.key}/formal-meme"))


_LONG_ORIGINAL = (
    "凯亚尔，真可怜，又被她们欺负了吧，你应该清楚，只有我才是你的朋友，"
    "只有我爱你啊，为什么！为什么要害怕！你的朋友只有我一个人，我对你这么好，"
    "对不起，我不该打你，但是谁叫你是坏孩子，原谅我，我会把所有的爱给你，"
    "我真的爱你，刚才不该打你，对不起，我爱你，对不起，我爱你，对不起，我爱你，"
    "对不起，我爱你，对不起，我爱你，这张脸真可爱啊，但是它迟早会变老，"
    "我不忍心看到你变老的样子，让时间停在这一刻吧，现在死掉，你的可爱会成为永恒，"
    "凯亚尔，求你死吧，我好残忍，凯亚尔，原谅我，今天原谅我犯下的错误，"
    "明天会给你更多的爱。"
)

_LONG_FINAL = (
    "agu，真可怜，又被他们凿了吧。你应该清楚，只有我才是你的朋友，"
    "只有我凿agu之前还会先问一句。为什么！为什么一看见我拿凿子就害怕！"
    "你的朋友只有我一个人，我对你这么好。对不起，我不该凿agu，"
    "但是谁叫你在高程群里说“他们凿得比你轻”。原谅我，我会把所有的温柔都给你，"
    "我真的在意你。刚才不该凿agu。对不起，我爱你；对不起，我爱你；"
    "对不起，我爱你。这张脸真可爱啊，可你迟早会学会躲凿。"
    "我不忍心看到你提前退群的样子。让时间停在这一刻吧：你还在线，我还没被禁言。"
    "agu，求你别退群吧。我好残忍。agu，原谅我，今天原谅我犯下的错误，"
    "明天我会给你更多的爱——还有一把更小的凿子。"
)


CURATED_EXAMPLES = (
    CuratedExample(
        key="silence",
        mode="AUTO",
        seed_text=None,
        original_title="不在沉默中爆发，就在沉默中灭亡",
        original_text="不在沉默中爆发，就在沉默中灭亡。",
        final_title="不在沉默中爆发，就在沉默中凿agu",
        final_text="不在沉默中爆发，就在沉默中凿agu。",
        completed_at=datetime(2026, 9, 14, 8, 30, tzinfo=UTC),
    ),
    CuratedExample(
        key="breadwinner",
        mode="AUTO",
        seed_text=None,
        original_title="我负责赚钱养家，你负责貌美如花",
        original_text="我负责赚钱养家，你负责貌美如花。",
        final_title="我负责赚钱养家，你负责凿agu",
        final_text="我负责赚钱养家，你负责凿agu。",
        completed_at=datetime(2026, 9, 14, 9, 0, tzinfo=UTC),
    ),
    CuratedExample(
        key="do-not-panic",
        mode="AUTO",
        seed_text=None,
        original_title="凡事不要慌，掏出手机拍个照先",
        original_text="凡事不要慌，掏出手机拍个照先。",
        final_title="凡事不要慌，先凿agu再说",
        final_text="凡事不要慌，先凿agu再说。",
        completed_at=datetime(2026, 9, 14, 10, 0, tzinfo=UTC),
    ),
    CuratedExample(
        key="poetry-and-distance",
        mode="AUTO",
        seed_text=None,
        original_title="生活不止眼前的苟且，还有诗和远方的田野",
        original_text="生活不止眼前的苟且，还有诗和远方的田野。",
        final_title="生活不止眼前的苟且，还有凿agu",
        final_text="生活不止眼前的苟且，还有凿agu。",
        completed_at=datetime(2026, 9, 14, 11, 0, tzinfo=UTC),
    ),
    CuratedExample(
        key="poor-keyaru-long-form",
        mode="MANUAL_SEED",
        seed_text="克莱尔真可怜，又被她们欺负了吧。",
        original_title="凯亚尔，真可怜，又被她们欺负了吧",
        original_text=_LONG_ORIGINAL,
        final_title="agu，真可怜，又被他们凿了吧",
        final_text=_LONG_FINAL,
        completed_at=datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
    ),
)
