def fallback_hash_frame(scene):
    hashes = [
        "l1{:f}-l2{:f}-l3{:f}-r1{:f}-r2{:f}-r3{:f}-s1{:f}-s2{:f}-s3{:f}".format(
            *object.location, *object.rotation_euler, *object.scale
        )
        for object in scene.objects
    ]

    return "".join(hashes)


def hash_frame(scene):
    slopes = []

    def process(value):
        if not (
            hasattr(value, "animation_data")
            and value.animation_data
            and value.animation_data.action
        ):
            return

        for fcurve in value.animation_data.action.fcurves:
            frame = scene.frame_current
            current = fcurve.evaluate(frame)
            next = fcurve.evaluate(frame + 1)
            slopes.append(next - current)

    for object in scene.objects:
        # object animations
        process(object)

        # modifier animations
        for modifier in object.modifiers:
            process(modifier)

        for slot in object.material_slots:
            if not slot.material:
                continue
            material = slot.material

            # material animations
            process(material)

            # node tree animations
            if material.use_nodes:
                process(material.node_tree)

    if len(slopes) < 1:
        return fallback_hash_frame(scene)

    return " ".join([str(slope) for slope in slopes])
