from kokoro_tts.text_segmenter import segment_text_natural


def test_english_sentence_does_not_split_inside_words():
    text = "Other times, it is fierce, roaring through the trees as if trying to wake the earth from a long slumber."
    segments = segment_text_natural(text, max_text_length=1000, segment_length=45)
    joined = " ".join(segments)
    assert "f ierce" not in joined
    assert "fierce" in joined
    assert all("ierce" != item.strip() for item in segments)


def test_periods_in_ip_version_and_decimal_are_not_boundaries():
    text = "版本 v2.6.5.0 在 192.168.1.1 上运行，金额是 4.20 元。然后继续说。"
    segments = segment_text_natural(text, max_text_length=1000, segment_length=28)
    joined = "".join(segments)
    assert "v2.6.5.0" in joined
    assert "192.168.1.1" in joined
    assert "4.20" in joined


def test_chinese_long_text_uses_punctuation_before_hard_cut():
    text = "这是第一句话。这里是一段比较长的中文内容，需要尽量按照逗号、顿号和句号来切分，避免听起来一顿一顿。最后结束。"
    segments = segment_text_natural(text, max_text_length=1000, segment_length=34)
    assert len(segments) >= 3
    assert all(item.strip() for item in segments)
    assert "这是第一句话。" in segments[0]


def test_paragraph_boundary_is_preserved_as_flush_point():
    text = "标题\n\n第一段内容比较短。\n\n第二段内容也比较短。"
    segments = segment_text_natural(text, max_text_length=1000, segment_length=80)
    assert segments == ["标题", "第一段内容比较短。", "第二段内容也比较短。"]


def test_auto_single_newline_merges_web_hard_wraps():
    text = "这是从网页复制出来的第一行\n这里其实还是同一段内容\n最后一句才结束。"
    segments = segment_text_natural(text, max_text_length=1000, segment_length=120)
    joined = "".join(segments)
    assert "第一行这里其实" in joined
    assert len(segments) == 1


def test_preserve_single_newline_keeps_manual_breaks():
    text = "标题\n第一段内容\n第二段内容"
    segments = segment_text_natural(text, max_text_length=1000, segment_length=120, single_newline_policy="preserve")
    assert segments == ["标题", "第一段内容", "第二段内容"]
