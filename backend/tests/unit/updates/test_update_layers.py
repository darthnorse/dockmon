"""Containers sharing a network namespace update dependents first."""

from types import SimpleNamespace

from updates.dependency_analyzer import update_layers

HOST_A = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
HOST_B = "f5cc8d91-318e-4a42-9ebc-bfe584f3a3b0"
PROVIDER_ID = "16678699c163"
PROVIDER_FULL_ID = PROVIDER_ID + "4a7e0fb11255730d62d4f39be4ef58f6f8eaa996a2bf593904"


def container(name, short_id, network_mode=None, host_id=HOST_A):
    return SimpleNamespace(
        name=name, id=short_id, short_id=short_id, host_id=host_id, network_mode=network_mode
    )


def names(layers):
    return [[c.name for c in layer] for layer in layers]


def test_dependent_goes_first_with_no_docker_client_involved():
    provider = container("gluetun", PROVIDER_ID, "bridge")
    dependent = container("qbittorrent", "395e946d84cc", f"container:{PROVIDER_FULL_ID}")

    assert names(update_layers([provider, dependent])) == [["qbittorrent"], ["gluetun"]]


def test_provider_is_matched_by_name_short_id_and_full_id():
    provider = container("gluetun", PROVIDER_ID)
    for ref in ("gluetun", PROVIDER_ID, PROVIDER_FULL_ID):
        dependent = container("qbittorrent", "395e946d84cc", f"container:{ref}")
        assert names(update_layers([provider, dependent])) == [["qbittorrent"], ["gluetun"]], ref


def test_pairs_are_per_host():
    layers = update_layers([
        container("gluetun", PROVIDER_ID, host_id=HOST_A),
        container("qbittorrent", "395e946d84cc", "container:gluetun", host_id=HOST_A),
        container("gluetun", "090c0da36612", host_id=HOST_B),
        container("qbittorrent", "5f9ef4057191", "container:gluetun", host_id=HOST_B),
    ])

    assert names(layers) == [["qbittorrent", "qbittorrent"], ["gluetun", "gluetun"]]


def test_same_short_id_on_two_hosts_is_not_a_link():
    provider_elsewhere = container("gluetun", PROVIDER_ID, host_id=HOST_B)
    dependent = container("qbittorrent", "395e946d84cc", f"container:{PROVIDER_FULL_ID}", host_id=HOST_A)

    assert len(update_layers([provider_elsewhere, dependent])) == 1


def test_other_network_modes_are_unlinked():
    provider = container("gluetun", PROVIDER_ID)
    for mode in (None, "", "bridge", "host", "none", "my_network", "container:aaaaaaaaaaaa"):
        other = container("other", "395e946d84cc", mode)
        assert len(update_layers([provider, other])) == 1, mode


def test_several_dependents_share_a_layer_with_unrelated_containers():
    layers = update_layers([
        container("gluetun", PROVIDER_ID),
        container("qbittorrent", "395e946d84cc", "container:gluetun"),
        container("sabnzbd", "67c5d2141338", "container:gluetun"),
        container("radarr", "e14c178c18f0", "bridge"),
    ])

    assert names(layers) == [["qbittorrent", "sabnzbd", "radarr"], ["gluetun"]]


def test_chain_goes_deepest_first():
    layers = update_layers([
        container("a", "aaaaaaaaaaaa"),
        container("b", "bbbbbbbbbbbb", "container:a"),
        container("c", "cccccccccccc", "container:b"),
    ])

    assert names(layers) == [["c"], ["b"], ["a"]]


def test_empty_and_single():
    assert update_layers([]) == []
    assert names(update_layers([container("a", "aaaaaaaaaaaa")])) == [["a"]]


def test_cycle_drops_nothing():
    layers = update_layers([
        container("a", "aaaaaaaaaaaa", "container:b"),
        container("b", "bbbbbbbbbbbb", "container:a"),
        container("c", "cccccccccccc"),
    ])

    assert sorted(c.name for layer in layers for c in layer) == ["a", "b", "c"]


def test_a_container_is_not_its_own_provider():
    assert len(update_layers([container("a", "aaaaaaaaaaaa", "container:a")])) == 1
