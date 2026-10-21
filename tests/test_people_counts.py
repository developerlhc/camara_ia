from vigilay.media_routes import summarize_people


def test_summarize_people_uses_crossings_not_peak_presence():
    result = summarize_people(
        [
            {
                "camera_id": "entrada",
                "camera_name": "Entrada",
                "persons_crossed": 2,
                "crossings_down": 1,
                "crossings_up": 1,
                "persons_visible_peak": 9,
            },
            {
                "camera_id": "entrada",
                "camera_name": "Entrada",
                "persons_crossed": 1,
                "crossings_down": 1,
            },
            {"camera_id": "caja", "camera_name": "Caja", "persons_visible_peak": 4},
        ]
    )

    assert result["persons_crossed"] == 3
    assert result["crossings_down"] == 2
    assert result["crossings_up"] == 1
    assert result["cameras"][0]["camera_id"] == "entrada"
    assert result["cameras"][1]["persons_crossed"] == 0
