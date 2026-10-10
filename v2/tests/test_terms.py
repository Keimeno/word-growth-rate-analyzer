from wgra.text import DOMAIN, PHRASE, SUBREDDIT, WORD, extract_terms


def words(text: str, language: str = "en") -> list[str]:
    counts = extract_terms(text, language).counts
    return sorted(term for kind, term in counts if kind == WORD)


def phrases(text: str, language: str = "en") -> list[str]:
    counts = extract_terms(text, language).counts
    return sorted(term for kind, term in counts if kind == PHRASE)


def of_kind(text: str, kind: str) -> list[str]:
    return sorted(term for k, term in extract_terms(text).counts if k == kind)


def test_words_are_lowercased_and_split_on_any_whitespace():
    assert words("Hello\nWorld\tagain  ok") == ["again", "hello", "ok", "world"]


def test_unicode_letters_survive():
    assert words("Für Straße Ärger") == ["für", "straße", "ärger"]


def test_inner_apostrophes_hyphens_and_dots_are_kept():
    assert words("don't use gpt-5 with node.js") == ["don't", "gpt-5", "node.js", "use", "with"]


def test_possessive_s_is_removed():
    assert words("Apple's new headset") == ["apple", "headset", "new"]


def test_typographic_apostrophes_are_normalized():
    assert words("don\u2019t") == ["don't"]


def test_sentence_punctuation_is_not_part_of_words():
    assert words("It works. Really, it does!") == ["does", "it", "really", "works"]


def test_occurrences_are_counted():
    counts = extract_terms("rust rust rust go").counts
    assert counts[WORD, "rust"] == 3
    assert counts[WORD, "go"] == 1


def test_token_count_counts_words_only():
    assert extract_terms("Check https://github.com/foo out, r/rust is nice").token_count == 4


def test_phrases_do_not_start_or_end_with_stopwords():
    assert phrases("the right to repair matters") == ["repair matters", "right to repair"]


def test_phrases_do_not_cross_sentence_boundaries():
    result = phrases("I bought a vision pro. Headset sales are up")
    assert "vision pro" in result
    assert "pro headset" not in result
    assert "headset sales" in result


def test_phrases_keep_numbers_but_need_a_letter():
    assert "rtx 5090" in phrases("the rtx 5090 is out")
    assert "2024 2025" not in phrases("from 2024 2025 on")


def test_phrases_are_limited_to_max_ngram():
    counts = extract_terms("alpha beta gamma delta", max_ngram=2).counts
    assert (PHRASE, "alpha beta") in counts
    assert (PHRASE, "alpha beta gamma") not in counts


def test_german_stopwords_apply_in_german_subreddits():
    assert "für das" not in phrases("gut für das klima", language="de")
    assert "gut für das klima" not in phrases("gut für das klima", language="de")
    assert "das klima" not in phrases("gut für das klima", language="de")


def test_urls_become_domains_and_leave_no_words():
    text = "see https://www.github.com/foo/bar?x=1 and [docs](https://docs.python.org/3/)"
    assert of_kind(text, DOMAIN) == ["docs.python.org", "github.com"]
    assert words(text) == ["and", "docs", "see"]


def test_bare_www_urls_are_domains():
    assert of_kind("go to www.example.com/page.", DOMAIN) == ["example.com"]


def test_subreddit_mentions_become_subreddit_terms():
    text = "Ask in r/LocalLLaMA or /r/selfhosted"
    assert of_kind(text, SUBREDDIT) == ["r/localllama", "r/selfhosted"]
    assert "localllama" not in words(text)


def test_user_mentions_are_dropped():
    assert words("thanks u/SomeUser and /u/other_one") == ["and", "thanks"]


def test_quotes_and_code_are_ignored():
    text = "> quoted claim\nmy reply\n```\nprint(secret_code)\n```\nuse `inline_thing` here"
    assert words(text) == ["here", "my", "reply", "use"]


def test_html_entities_and_zero_width_spaces_are_removed():
    assert words("&amp;#x200B;​hello &amp; bye") == ["bye", "hello"]


def test_overlong_tokens_are_dropped():
    assert words("a" * 41 + " fine") == ["fine"]


def test_empty_text():
    terms = extract_terms("")
    assert terms.token_count == 0
    assert not terms.counts
