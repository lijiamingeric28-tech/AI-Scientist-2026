from astroquery_ai.api.windows_frame import chrome_metrics, resize_hit


def test_native_chrome_scales_without_changing_webview_css():
    for dpi, height, width in [(96, 32, 46), (120, 40, 58), (144, 48, 69)]:
        m = chrome_metrics(dpi)
        assert (m['height'], m['button_width']) == (height, width)
        assert 3 * width < 1000 * dpi / 96


def test_resize_hit_preserves_corners_and_caption_drag():
    assert resize_hit(1, 1, 1000, 700, 5) == 13
    assert resize_hit(999, 1, 1000, 700, 5) == 14
    assert resize_hit(1, 699, 1000, 700, 5) == 16
    assert resize_hit(999, 699, 1000, 700, 5) == 17
    assert resize_hit(500, 699, 1000, 700, 5) == 15
    assert resize_hit(500, 20, 1000, 700, 5) == 2
