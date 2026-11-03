import pytest

from cropplan_jobs.cli import parse


def test_solve_flags_use_the_yaml_spelling_and_optional_ones_default_empty():
    args = parse("cropplan-solve", ["--catalog=c", "--schema=s", "--experiment=/Shared/e", "--scenario_id=b",
                                    "--job_run_id=12", "--run_id="])
    assert (args.scenario_id, args.run_id, args.triggered_by, args.job_run_id) == ("b", "", "", "12")


def test_pushed_down_job_parameters_are_ignored(capsys):
    # stress_test's load task receives the job's scenario_id/n/seed/... although it declares none of them.
    args = parse("cropplan-stress-load", ["--catalog=c", "--schema=s", "--volume_root=/Volumes/c/s/stress",
                                          "--job_run_id=7", "--scenario_id=b", "--n=20", "--seed=2027"])
    assert (args.volume_root, args.job_run_id) == ("/Volumes/c/s/stress", "7")
    assert "IGNORED_JOB_PARAMETERS" in capsys.readouterr().out


def test_hyphenated_flags_are_rejected_loudly():
    with pytest.raises(SystemExit):
        parse("cropplan-solve", ["--catalog=c", "--schema=s", "--experiment=e", "--scenario-id=b", "--job_run_id=1"])


def test_required_flags_are_required():
    with pytest.raises(SystemExit):
        parse("cropplan-stress-load", ["--catalog=c", "--schema=s"])


def test_volume_root_must_be_the_bundle_stress_volume():
    from cropplan_jobs.cli import check_volume_root
    assert check_volume_root("/Volumes/c/s/stress", "c", "s") == "/Volumes/c/s/stress"
    for bad in ("/Volumes/c/s/stress/../../other", "/Workspace/Users/x", "/Volumes/c/other/stress", ""):
        with pytest.raises(ValueError, match="volume_root"):
            check_volume_root(bad, "c", "s")


@pytest.mark.parametrize("entry, argv", [
    ("stress_prepare", ["--catalog=c", "--schema=s", "--volume_root=/Workspace/x", "--scenario_id=b",
                        "--n=20", "--seed=2027", "--stress_id=", "--job_run_id=7", "--triggered_by="]),
    ("stress_load", ["--catalog=c", "--schema=s", "--volume_root=/Workspace/x", "--job_run_id=7"]),
])
def test_stress_entry_points_reject_foreign_volume_root_before_touching_spark(entry, argv, monkeypatch):
    import sys

    from cropplan_jobs import cli

    def no_spark(_args):
        raise AssertionError("opened Spark before checking volume_root")

    monkeypatch.setattr(cli, "_store", no_spark)
    monkeypatch.setattr(sys, "argv", [entry, *argv])
    with pytest.raises(ValueError, match="volume_root"):
        getattr(cli, entry)()
