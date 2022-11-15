#include <fstream>
#include <iostream>
#include <ostream>
#include <vector>

#include "acl/decompression/decompress.h"
#include "acl/decompression/decompression_settings.h"

using namespace acl;

struct vector
{
	float x, y, z;
};

struct quat
{
	float x, y, z, w;
};

struct transform
{
	quat rotation;
	vector translation, scale;

	void RTM_SIMD_CALL set_rotation_raw(rtm::quatf_arg0 rotation_)
	{
		rtm::quat_store(rotation_, &rotation.x);
	}

	void RTM_SIMD_CALL set_translation_raw(rtm::vector4f_arg0 translation_)
	{
		rtm::vector_store3(translation_, &translation.x);
	}

	void RTM_SIMD_CALL set_scale_raw(rtm::vector4f_arg0 scale_)
	{
		rtm::vector_store3(scale_, &scale.x);
	}
};

struct atom_indices
{
	uint16_t rotation;
	uint16_t translation;
	uint16_t scale;
};

struct frontiers_writer final : public track_writer
{
	//////////////////////////////////////////////////////////////////////////
// For performance reasons, this writer skips all default sub-tracks.
// It is the responsibility of the caller to pre-populate them by calling initialize_with_defaults().
	static constexpr acl::default_sub_track_mode get_default_rotation_mode() { return acl::default_sub_track_mode::skipped; }
	static constexpr acl::default_sub_track_mode get_default_translation_mode() { return acl::default_sub_track_mode::skipped; }
	static constexpr acl::default_sub_track_mode get_default_scale_mode() { return acl::default_sub_track_mode::skipped; }

	explicit frontiers_writer(std::vector<rtm::qvvf>& Transforms_) : Transforms(Transforms_) {}

	std::vector<rtm::qvvf>& Transforms;

	//////////////////////////////////////////////////////////////////////////
	// Called by the decoder to write out a quaternion rotation value for a specified bone index.
	void RTM_SIMD_CALL write_rotation(uint32_t TrackIndex, rtm::quatf_arg0 Rotation)
	{
		Transforms[TrackIndex].rotation = Rotation;
	}

	//////////////////////////////////////////////////////////////////////////
	// Called by the decoder to write out a translation value for a specified bone index.
	void RTM_SIMD_CALL write_translation(uint32_t TrackIndex, rtm::vector4f_arg0 Translation)
	{
		Transforms[TrackIndex].translation = Translation;
	}

	//////////////////////////////////////////////////////////////////////////
	// Called by the decoder to write out a scale value for a specified bone index.
	void RTM_SIMD_CALL write_scale(uint32_t TrackIndex, rtm::vector4f_arg0 Scale)
	{
		Transforms[TrackIndex].scale = Scale;
	}
};

struct anim_output
{
	float duration;
	uint32_t frame_count;
	uint32_t bone_count;
	std::vector<std::vector<rtm::qvvf>> all_tracks;
};

static bool anim_to_buffer(const char* filename, const char*& out_buffer, size_t& out_buffer_size)
{
	FILE* file;

	//Open file
	file = fopen(filename, "rb");
	if (!file)
	{
		fprintf(stderr, "Unable to open file %s", filename);
		return false;
	}

	//Get file length
	fseek(file, 0, SEEK_END);
	out_buffer_size = ftell(file) - 0x80 - 0x34;
	fseek(file, 0x80, SEEK_SET);

	//Allocate memory
	out_buffer = (char*)malloc(out_buffer_size + 1);
	if (!out_buffer)
	{
		fprintf(stderr, "Memory error!");
		fclose(file);
		return false;
	}

	//Read file contents into buffer
	fread((void*)out_buffer, out_buffer_size, 1, file);
	fclose(file);
	return true;
}

int main(int argc, char* argv[])
{
	if (argc != 2)
	{
		std::cout << "Invalid arguments! PXD should be the only argument" << std::endl;
		return 1;
	}

    decompression_context<default_transform_decompression_settings> context;

	const char* buffer = nullptr;
	size_t buffer_size = 0;

	if (!anim_to_buffer(argv[1], buffer, buffer_size))
	{
		std::cout << "Failed to read file to buffer" << std::endl;
		return 1;
	}
	
	error_result result;

	const compressed_tracks* compressed_anim = make_compressed_tracks(buffer, &result);

    if (!context.initialize(*compressed_anim))
    {
		std::cout << "Failed to read anim: " << result.c_str() << std::endl;
    	return 1;
    }
	std::vector<rtm::qvvf> raw_local_pose_transforms;

	for (uint32_t i = 0; i < compressed_anim->get_num_tracks(); i++)
	{
		raw_local_pose_transforms.push_back(rtm::qvvf());
	}

	frontiers_writer writer(raw_local_pose_transforms);

	std::vector<std::vector<rtm::qvvf>> all_tracks;

	for (uint32_t sample_index = 0; sample_index < compressed_anim->get_num_samples_per_track(); ++sample_index)
	{
		const float sample_time = rtm::scalar_min(float(sample_index) / compressed_anim->get_sample_rate(), compressed_anim->get_duration());

		context.seek(sample_time, acl::sample_rounding_policy::none);
		context.decompress_tracks(writer);
		all_tracks.push_back(writer.Transforms);
	}

	std::cout << "Decompressed tracks" << std::endl;

	anim_output output;

	output.duration = compressed_anim->get_duration();
	output.frame_count = compressed_anim->get_num_samples_per_track();
	output.bone_count = compressed_anim->get_num_tracks();
	output.all_tracks = all_tracks;

	char* out_name = (char*)malloc(strlen(argv[1]) + 7);
	strcpy(out_name, argv[1]);
	strcat(out_name, ".outanim");
	
	std::ofstream wf(out_name, std::ios::out | std::ios::binary);
	if (!wf) {
		std::cout << "Cannot open file!" << std::endl;
		return 1;
	}
	wf.write((char*)&output.duration, sizeof(float));
	wf.write((char*)&output.frame_count, sizeof(uint32_t));
	wf.write((char*)&output.bone_count, sizeof(uint32_t));
	
	for (uint32_t i = 0; i < output.all_tracks.size(); i++)
	{
		wf.write((char*)output.all_tracks[i].data(), sizeof rtm::qvvf * output.all_tracks[i].size());
	}
	wf.close();

    return 0;
}