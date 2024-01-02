#include <fstream>
#include <iostream>
#include <ostream>
#include <vector>

#include "acl/compression/compress.h"
#include "acl/compression/compression_settings.h"
#include "acl/compression/output_stats.h"
#include "acl/compression/track_array.h"
#include "acl/core/ansi_allocator.h"
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

static bool compressed_anim_to_buffer(const char* filename, const char*& out_buffer, size_t& out_buffer_size, uint32_t offset_loc)
{
	FILE* file;

	//Open file
	file = fopen(filename, "rb");
	if (!file)
	{
		fprintf(stderr, "Unable to open file %s \n", filename);
		return false;
	}

	//Find buffer, get buffer length
	uint32_t out_buffer_offset;
	fseek(file, offset_loc, SEEK_SET);
	fread(&out_buffer_offset, sizeof(out_buffer_offset), 1, file);
	fseek(file, out_buffer_offset + 0x40, SEEK_SET);
	fread(&out_buffer_size, 4, 1, file);
	fseek(file, out_buffer_offset + 0x40, SEEK_SET);


	//Allocate memory
	out_buffer = (char*)malloc(out_buffer_size + 1);
	if (!out_buffer)
	{
		fprintf(stderr, "Memory error! \n");
		fclose(file);
		return false;
	}

	//Read file contents into buffer
	fread((void*)out_buffer, out_buffer_size, 1, file);
	fclose(file);
	return true;
}

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
	out_buffer_size = ftell(file);
	fseek(file, 0, SEEK_SET);

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

bool decompress(char* filename, uint32_t data_offset)
{
    decompression_context<default_transform_decompression_settings> context;

	const char* buffer = nullptr;
	size_t buffer_size = 0;

	if (!compressed_anim_to_buffer(filename, buffer, buffer_size, data_offset))
	{
		std::cout << "Failed to read file to buffer" << std::endl;
		return false;
	}
	
	error_result result;

	const compressed_tracks* compressed_anim = make_compressed_tracks(buffer, &result);

    if (!context.initialize(*compressed_anim))
    {
		std::cout << "Failed to read anim: " << result.c_str() << std::endl;
		return false;
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

	char* out_name;
	char* suffix_pxd = strstr(filename, ".pxd");
	if (suffix_pxd != NULL && strcmp(suffix_pxd, ".pxd") == 0) {
		char* suffix_anm_pxd = strstr(filename, ".anm.pxd");
		int new_len;
		if (suffix_anm_pxd != NULL && strcmp(suffix_anm_pxd, ".anm.pxd") == 0) {
			new_len = strlen(filename) - strlen(".anm.pxd");
		}
		else {
			new_len = strlen(filename) - strlen(".pxd");
		}
		out_name = (char*)malloc(new_len + 1 + strlen(".outanim"));
		strncpy(out_name, filename, new_len);
		out_name[new_len] = '\0';
	}
	else {
		out_name = (char*)malloc(strlen(filename) + 1);
		strcpy(out_name, filename);
	}
	strcat(out_name, ".outanim");
	
	std::ofstream wf(out_name, std::ios::out | std::ios::binary);
	if (!wf) {
		std::cout << "Cannot open file!" << std::endl;
		return false;
	}
	wf.write((char*)&output.duration, sizeof(float));
	wf.write((char*)&output.frame_count, sizeof(uint32_t));
	wf.write((char*)&output.bone_count, sizeof(uint32_t));
	
	for (uint32_t i = 0; i < output.all_tracks.size(); i++)
	{
		wf.write((char*)output.all_tracks[i].data(), sizeof rtm::qvvf * output.all_tracks[i].size());
	}
	wf.close();
	
	std::cout << "File written" << std::endl;

	return true;
}

#pragma optimize("", off) 
bool compress(char* filename)
{
	const char* buffer = nullptr;
	size_t buffer_size = 0;

	if (!anim_to_buffer(filename, buffer, buffer_size))
	{
		std::cout << "Failed to read file to buffer" << std::endl;
		return false;
	}

	float duration = *(float*)&buffer[0];
	uint32_t sample_count = *(uint32_t*)&buffer[4];
	float sample_rate = (float)(sample_count - 1) / duration;
	uint32_t track_count = *(uint32_t*)&buffer[8];

	ansi_allocator allocator;
	track_array_qvvf raw_track_list(allocator, track_count);
	
	for (uint32_t i = 0; i < track_count; i++)
	{
		std::vector<rtm::qvvf> track;
		for (uint32_t j = 0; j < sample_count; j++)
		{
			uint32_t file_pos = 0xC + j * track_count * sizeof rtm::qvvf + i * sizeof rtm::qvvf;
			rtm::qvvf transform = *(rtm::qvvf*)&buffer[file_pos];
			track.push_back(transform);
		}

		track_desc_transformf desc;
		desc.output_index = i;
		desc.precision = 0.001f;
		desc.shell_distance = 3.f;
		track_qvvf raw_track = track_qvvf::make_reserve(desc, allocator, sample_count, sample_rate);
		for (uint32_t j = 0; j < sample_count; j++)
		{
			raw_track[j] = track[j];
		}
		raw_track_list[i] = std::move(raw_track);
	}
	
	std::cout << "Tracks read" << std::endl;
	
	compression_settings settings;
	settings.level = compression_level8::highest;
	settings.rotation_format = rotation_format8::quatf_drop_w_variable;
	settings.translation_format = vector_format8::vector3f_variable;
	settings.scale_format = vector_format8::vector3f_variable;

	qvvf_transform_error_metric error_metric;
	settings.error_metric = &error_metric;

	output_stats stats;
	compressed_tracks* out_compressed_tracks = nullptr;
	error_result result = compress_track_list(allocator, raw_track_list, settings, out_compressed_tracks, stats);

	if (out_compressed_tracks == nullptr)
	{
		std::cout << "Failed to compress anim: " << result.c_str() << std::endl;
		return false;
	}
	
	std::cout << "Compressed tracks" << std::endl;

	char* out_name;
	char* suffix_outanim = strstr(filename, ".outanim");
	if (suffix_outanim != NULL && strcmp(suffix_outanim, ".outanim") == 0) {
		size_t new_len = strlen(filename) - strlen(".outanim");
		out_name = (char*)malloc(new_len + 1 + strlen(".anm.pxd"));
		strncpy(out_name, filename, new_len);
		out_name[new_len] = '\0';
	}
	else {
		out_name = (char*)malloc(strlen(filename) + 1 + strlen(".anm.pxd"));
		strcpy(out_name, filename);
	}
	strcat(out_name, ".anm.pxd");
	
	std::ofstream wf(out_name, std::ios::out | std::ios::binary);
	if (!wf) {
		std::cout << "Cannot open file!" << std::endl;
		return false;
	}

	//BINA/DATA header
	unsigned int num = 0;
	wf.write("BINA210L", 8);
	num = out_compressed_tracks->get_size() + 0x80 + 0x10 - out_compressed_tracks->get_size() % 0x10 + 0xC;;
	wf.write((char*)&num, 0x4);
	num = 1;
	wf.write((char*)&num, 0x4);
	wf.write("DATA", 4);
	num = out_compressed_tracks->get_size() + 0x70 + 0x10 - out_compressed_tracks->get_size() % 0x10 + 0xC;;
	wf.write((char*)&num, 0x4);
	num -= 0x34;
	wf.write((char*)&num, 0x4);
	num = 0;
	wf.write((char*)&num, 0x4);
	num = 4;
	wf.write((char*)&num, 0x4);
	num = 0x18;
	wf.write((char*)&num, 0x4);
	num = 0;
	for (int i = 0; i < 6; i++)
		wf.write((char*)&num, 0x4);

	//PXAN header
	wf.write("NAXP", 4);
	num = 512;
	wf.write((char*)&num, 0x4);
	num = 2048;
	wf.write((char*)&num, 0x4);
	num = 0;
	wf.write((char*)&num, 0x4);
	num = 24;
	wf.write((char*)&num, 0x4);
	num = 0;
	wf.write((char*)&num, 0x4);
	wf.write((char*)&duration, 4);
	wf.write((char*)&sample_count, 4);
	wf.write((char*)&track_count, 4);
	num = 0;
	wf.write((char*)&num, 0x4);
	num = 64;
	wf.write((char*)&num, 0x4);
	num = 0;
	wf.write((char*)&num, 0x4);
	num = out_compressed_tracks->get_size() + 0x70 + 0x10 - out_compressed_tracks->get_size() % 0x10;
	wf.write((char*)&num, 0x4);
	num = 0;
	wf.write((char*)&num, 0x4);
	wf.write((char*)&num, 0x4);
	wf.write((char*)&num, 0x4);
	wf.write((char*)out_compressed_tracks, out_compressed_tracks->get_size());
	num = 0;
	for (unsigned int i = 0; i < 0x10 - out_compressed_tracks->get_size() % 0x10; i++)
		wf.write((char*)&num, 1);
	num = 0xFFFFFFFF;
	wf.write((char*)&num, 0x4);
	num = 0;
	wf.write((char*)&num, 0x4);
	num = 0x00424644;
	wf.write((char*)&num, 0x4);
	wf.close();
	
	std::cout << "Wrote file" << std::endl;

	return true;
}
#pragma optimize("", on) 

int main(int argc, char* argv[])
{
	if (argc != 2)
	{
		std::cout << "Invalid arguments! The animation file should be the only argument. For decompression, this is the .anm.pxd. For compression, this is the .outanim." << std::endl;
		return 1;
	}
	const char *dot = strrchr(argv[1], '.');
	if(!dot || dot == argv[1])
	{
		std::cout << "Invalid arguments! The animation file should be the only argument. For decompression, this is the .anm.pxd. For compression, this is the .outanim." << std::endl;
		return 1;
	}

	if (!strcmp(dot, ".pxd"))
	{
		if (!decompress(argv[1], 0x68))
			return 1;
	}
	else if (!strcmp(dot, ".outanim"))
	{
		if (!compress(argv[1]))
			return 1;
	}
	else
	{
		std::cout << "Invalid arguments! The animation file should be the only argument. For decompression, this is the .anm.pxd. For compression, this is the .outanim." << std::endl;
		return 1;
	}
	
    return 0;
}
