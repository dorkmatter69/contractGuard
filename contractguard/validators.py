"""Small deterministic acceptance rule; version changes require a new registry key."""
def episode_v1(artifact):
    return (isinstance(artifact, dict) and set(artifact) == {'episodes', 'successful'}
            and type(artifact['episodes']) is int and type(artifact['successful']) is int
            and artifact['episodes'] >= 10
            and 0 <= artifact['successful'] <= artifact['episodes']
            and artifact['successful'] * 10 >= artifact['episodes'] * 9)


REGISTRY = {'episode/v1': episode_v1}
