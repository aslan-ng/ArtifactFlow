from __future__ import annotations


def io_match_score_equation(
    matches: int,
    missing_inputs: int,
    missing_input_penalty_ratio: float | int = 1.0,
) -> float:
    """
    Score how well outputs cover inputs.
    Unused outputs are ignored.

    missing_input_penalty_ratio:
        0.0 -> missing inputs are ignored
        1.0 -> ordinary input coverage
        >1.0 -> missing inputs are penalized more strongly
    """
    if matches < 0:
        raise ValueError("matches cannot be negative")

    if missing_inputs < 0:
        raise ValueError("missing_inputs cannot be negative")

    if missing_input_penalty_ratio < 0:
        raise ValueError(
            "missing_input_penalty_ratio cannot be negative"
        )
    
    numerator = matches
    denominator = (
        matches
        + missing_input_penalty_ratio * missing_inputs
    )

    if denominator == 0:
        return 0.0
    return numerator / denominator


if __name__ == "__main__":

    matches_list = [1, 2, 3, 4]
    missing_inputs_list = [1, 2, 3, 4]
    penalty_ratio_list = [0.0, 0.5, 1.0, 2.0]

    # Header
    print(
        f"{'Matches':>8} "
        f"{'Missing':>8}",
        end="",
    )

    for ratio in penalty_ratio_list:
        print(f" {f'Ratio={ratio}':>12}", end="")

    print()

    # Separator
    print("-" * (18 + 13 * len(penalty_ratio_list)))

    # Rows
    for matches in matches_list:
        for missing_inputs in missing_inputs_list:
            print(
                f"{matches:>8} "
                f"{missing_inputs:>8}",
                end="",
            )

            for ratio in penalty_ratio_list:
                score = io_match_score_equation(
                    matches=matches,
                    missing_inputs=missing_inputs,
                    missing_input_penalty_ratio=ratio,
                )

                print(f" {score:>12.3f}", end="")

            print()